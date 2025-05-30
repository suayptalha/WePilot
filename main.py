from huggingface_hub import InferenceClient
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import json
import time
import re
import random

client = InferenceClient(
    model="deepseek-ai/DeepSeek-V3-0324",
    provider="novita",
)

def configure_browser():
    options = webdriver.ChromeOptions()
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-blink-features=AutomationControlled")
    
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        })
        """
    })
    return driver

driver = configure_browser()

conversation_history = []

def preprocess_html(html, max_chars=5000):
    soup = BeautifulSoup(html, 'html.parser')
    
    for tag in ['script', 'style', 'meta', 'link', 'noscript', 'svg']:
        for element in soup.find_all(tag):
            element.decompose()

    search_inputs = []
    search_patterns = [
        {'type': 'search'},
        {'name': 'q'},
        {'placeholder': lambda x: x and isinstance(x, str) and 'search' in x.lower()},
        {'aria-label': lambda x: x and isinstance(x, str) and 'search' in x.lower()},
        {'class': lambda x: x and (isinstance(x, str) and ('search' in x.lower() or 'query' in x.lower()))},
        {'id': lambda x: x and isinstance(x, str) and ('search' in x.lower() or 'query' in x.lower())}
    ]
    
    for pattern in search_patterns:
        key, value = next(iter(pattern.items()))
        if callable(value):
            found = soup.find_all(lambda tag: tag.name in ['input', 'textarea'] and value(tag.get(key, '')))
        else:
            found = soup.find_all(['input', 'textarea'], {key: value})
        search_inputs.extend(found)
    
    interactive_tags = ['a', 'button', 'input', 'textarea', 'select']
    clickable_elements = soup.find_all(interactive_tags)
    
    clickable_elements.extend(soup.find_all(attrs={'onclick': True, 'role': ['button', 'link', 'tab']}))
    
    clickable_classes = ['btn', 'button', 'clickable', 'link', 'submit', 'nav-item']
    for cls in clickable_classes:
        clickable_elements.extend(soup.find_all(attrs={'class': lambda x: x and cls in x.split()}))
    
    processed_html = []
    
    for element in search_inputs:
        attributes = {
            'tag': element.name,
            'id': element.get('id'),
            'class': ' '.join(element.get('class', [])) if isinstance(element.get('class'), list) else element.get('class'),
            'name': element.get('name'),
            'type': element.get('type'),
            'placeholder': element.get('placeholder'),
            'aria-label': element.get('aria-label'),
            'role': element.get('role'),
            'text': element.get_text().strip()[:100] if element.get_text().strip() else None,
            'is_search': True,
            'is_visible': is_likely_visible(element),
            'location': get_element_location(element)
        }
        attributes = {k: v for k, v in attributes.items() if v is not None}
        
        if attributes:
            processed_html.append(str(attributes))
    
    for element in clickable_elements:
        if element in search_inputs:
            continue
            
        if not is_likely_visible(element):
            continue
            
        attributes = {
            'tag': element.name,
            'id': element.get('id'),
            'class': ' '.join(element.get('class', [])) if isinstance(element.get('class'), list) else element.get('class'),
            'name': element.get('name'),
            'type': element.get('type'),
            'placeholder': element.get('placeholder'),
            'aria-label': element.get('aria-label'),
            'role': element.get('role'),
            'text': element.get_text().strip()[:100] if element.get_text().strip() else None,
            'href': element.get('href'),
            'onclick': element.get('onclick'),
            'is_visible': True,
            'location': get_element_location(element)
        }
        attributes = {k: v for k, v in attributes.items() if v is not None}
        
        if attributes:
            processed_html.append(str(attributes))
    
    return '\n'.join(processed_html)[:max_chars]

def is_likely_visible(element):
    if element.get('hidden') or element.get('style') and ('display:none' in element['style'] or 'visibility:hidden' in element['style']):
        return False
    
    if element.get('width') == '0' or element.get('height') == '0':
        return False
    
    classes = element.get('class', [])
    if isinstance(classes, str):
        classes = classes.split()
    
    invisible_classes = ['hidden', 'invisible', 'collapsed', 'sr-only', 'visually-hidden']
    for cls in invisible_classes:
        if any(cls in c for c in classes):
            return False
    
    return True

def get_element_location(element):
    parent_tags = []
    parent = element.parent
    
    for _ in range(3):
        if parent and parent.name:
            parent_tags.append(parent.name)
            if parent.get('id'):
                parent_tags[-1] += f"#{parent.get('id')}"
            elif parent.get('class'):
                classes = parent.get('class')
                if isinstance(classes, list):
                    parent_tags[-1] += f".{'.'.join(classes)}"
                else:
                    parent_tags[-1] += f".{classes}"
            parent = parent.parent
        else:
            break
    
    return ' > '.join(reversed(parent_tags)) if parent_tags else None

few_shot_examples = """
Example 1:
Command: "Search for cat videos on YouTube"
Actions: [
    {"action": "navigate", "url": "https://www.youtube.com"},
    {"action": "find_and_click", "description": "Find and click the search box", 
     "element_properties": {"tag": "input", "aria-label": "Search", "placeholder": "Search"}},
    {"action": "type", "text": "cat videos", "use_previous_element": true},
    {"action": "press_enter", "use_previous_element": true}
]

Example 2:
Command: "Search for books on Amazon"
Actions: [
    {"action": "navigate", "url": "https://www.amazon.com"},
    {"action": "find_and_click", "description": "Find and click the search box", 
     "element_properties": {"tag": "input", "aria-label": "Search", "type": "text"}},
    {"action": "type", "text": "books", "use_previous_element": true},
    {"action": "find_and_click", "description": "Click search button", 
     "element_properties": {"tag": "input", "type": "submit"}}
]

Example 3:
Command: "Check the weather on Google"
Actions: [
    {"action": "navigate", "url": "https://www.google.com"},
    {"action": "find_and_click", "description": "Find and click the search box", 
     "element_properties": {"tag": "textarea", "aria-label": "Search"}},
    {"action": "type", "text": "weather forecast", "use_previous_element": true},
    {"action": "press_enter", "use_previous_element": true}
]
"""

def send_command_to_llm(command, html=None):
    global conversation_history
    
    system_message = {
        "role": "system", 
        "content": """You are a web automation agent. You understand user commands and can perform actions like navigating websites, finding elements dynamically, clicking, typing, etc.

Your primary task is to generate actions to complete web tasks. Instead of using fixed CSS selectors, you should identify elements based on their attributes like text content, aria-labels, placeholders, or other identifying features.

IMPORTANT: Always provide your responses in valid JSON format. Do not include any explanations, markdown formatting, or narrative text outside the JSON.

CRITICAL: Be aware of the current state of the browser. If you are already on a website, do not navigate to it again. Continue from the current page state.

Available actions:
- "navigate": Go to a specific URL (only use if not already on the site)
- "find_and_click": Find an element based on provided properties and click it
- "type": Type text into the previously found element
- "press_enter": Press Enter key on the previously found element
- "scroll": Scroll the page (specify direction: "up", "down", "to_top", "to_bottom" and amount in pixels)
- "scroll_to_element": Scroll until a specific element is visible
- "new_tab": Open a new browser tab
- "close_tab": Close the current tab
- "switch_tab": Switch to a different tab by index or URL
- "refresh_page": Refresh the current page
- "go_back": Navigate back in browser history
- "go_forward": Navigate forward in browser history
- "wait": Wait for a specific time
- "complete": Signal task completion

For finding elements, provide "element_properties" containing attributes that uniquely identify the element like:
- tag: The element's HTML tag (input, button, a, etc.)
- text: Visible text of the element
- id: Element's ID attribute
- class: Element's class attribute
- aria-label: Accessibility label
- placeholder: Placeholder text
- role: Element's role attribute

Example for finding a search box:
"element_properties": {"tag": "input", "aria-label": "Search", "placeholder": "Search"}
""" + few_shot_examples
    }

    try:
        current_url = driver.current_url
        page_title = driver.title
        current_tab_index = get_current_tab_index()
        tab_count = len(driver.window_handles)
        browser_state = f"Current browser state: URL={current_url}, Title={page_title}, Tab {current_tab_index+1} of {tab_count}"
    except:
        browser_state = "Browser state unknown"
    
    if html:
        user_message = {
            "role": "user", 
            "content": f"Command: {command}\nHTML Elements:\n{html}\n{browser_state}"
        }
    else:
        user_message = {
            "role": "user", 
            "content": f"Command: {command}\n{browser_state}"
        }
    
    messages = [system_message] + conversation_history + [user_message]
    
    if len(messages) > 10:
        messages = [system_message] + messages[-9:]
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                messages=messages,
                max_tokens=512,
                temperature=0.1
            )
            
            response = completion.choices[0].message.content
            
            json_content = extract_json_from_text(response)
            
            if json_content:
                conversation_history.append(user_message)
                conversation_history.append({"role": "assistant", "content": response})
                return json_content
            
            if attempt < max_retries - 1:
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user", 
                    "content": "Your response was not valid JSON. Please provide only a valid JSON response with no additional text or formatting. Format your response like: {\"actions\": [{\"action\": \"navigate\", ...}]}"
                })
        except Exception as e:
            print(f"API error on attempt {attempt+1}: {str(e)}")
            time.sleep(0.5)
    
    print("Failed to get valid JSON after multiple attempts.")
    return json.dumps({"actions": []})

def extract_json_from_text(text):
    try:
        json_obj = json.loads(text)
        return json_obj
    except json.JSONDecodeError:
        pass
    
    code_block_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    code_matches = re.findall(code_block_pattern, text)
    
    for match in code_matches:
        try:
            json_obj = json.loads(match)
            return json_obj
        except json.JSONDecodeError:
            continue
    
    json_pattern = r"{[\s\S]*}"
    json_matches = re.findall(json_pattern, text)
    
    for match in json_matches:
        try:
            json_obj = json.loads(match)
            return json_obj
        except json.JSONDecodeError:
            continue
    
    array_pattern = r"\[\s*{[\s\S]*}\s*\]"
    array_matches = re.findall(array_pattern, text)
    
    for match in array_matches:
        try:
            json_obj = json.loads(match)
            return json_obj
        except json.JSONDecodeError:
            continue
    
    return None

def find_element_by_properties(element_properties, timeout=0.5):
    is_search_element = element_properties.get('is_search', False) or (
        ('type' in element_properties and element_properties['type'] == 'search') or
        ('placeholder' in element_properties and isinstance(element_properties['placeholder'], str) and 'search' in element_properties['placeholder'].lower()) or
        ('aria-label' in element_properties and isinstance(element_properties['aria-label'], str) and 'search' in element_properties['aria-label'].lower()) or
        ('class' in element_properties and isinstance(element_properties['class'], str) and ('search' in element_properties['class'].lower() or 'query' in element_properties['class'].lower())) or
        ('id' in element_properties and isinstance(element_properties['id'], str) and ('search' in element_properties['id'].lower() or 'query' in element_properties['id'].lower()))
    )

    if is_search_element:
        fast_selectors = [
            "//textarea[@aria-label='Search']",
            "//input[@aria-label='Search']",
            "//input[@name='q']",
            "//input[@type='search']",
        ]
        for selector in fast_selectors:
            try:
                element = driver.find_element(By.XPATH, selector)
                if element.is_displayed():
                    return element
            except Exception:
                continue

    wait = WebDriverWait(driver, timeout)

    if 'id' in element_properties:
        try:
            element = wait.until(EC.element_to_be_clickable((By.ID, element_properties['id'])))
            return element
        except Exception:
            pass

    xpath_conditions = []
    tag = element_properties.get('tag', '*')
    for attr, value in element_properties.items():
        if attr == 'tag':
            continue
        elif attr == 'text':
            xpath_conditions.append(f"contains(text(), '{value}')")
        elif attr == 'class':
            if isinstance(value, list):
                for cls in value:
                    xpath_conditions.append(f"contains(@class, '{cls}')")
            else:
                for cls in value.split():
                    xpath_conditions.append(f"contains(@class, '{cls}')")
        else:
            xpath_conditions.append(f"@{attr}='{value}'")
    if xpath_conditions:
        xpath = f"//{tag}[{' and '.join(xpath_conditions)}]"
        try:
            element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
            return element
        except Exception:
            pass

    if is_search_element:
        common_search_selectors = [
            "//input[@type='search']",
            "//input[@name='q']",
            "//input[@aria-label='Search']",
            "//input[contains(@placeholder, 'search')]",
            "//input[contains(@placeholder, 'Search')]",
            "//input[contains(@class, 'search')]",
            "//textarea[contains(@placeholder, 'Search')]",
            "//textarea[@aria-label='Search']"
        ]
        for selector in common_search_selectors:
            try:
                element = driver.find_element(By.XPATH, selector)
                if element.is_displayed():
                    return element
            except Exception:
                continue

    if is_search_element:
        try:
            search_js = """
            var inputs = document.querySelectorAll('input, textarea');
            for (var i=0; i<inputs.length; i++) {
                var el = inputs[i];
                var type = el.getAttribute('type') || '';
                var placeholder = el.getAttribute('placeholder') || '';
                var aria = el.getAttribute('aria-label') || '';
                var name = el.getAttribute('name') || '';
                var id = el.getAttribute('id') || '';
                if (
                    type.toLowerCase() === 'search' ||
                    name.toLowerCase() === 'q' ||
                    placeholder.toLowerCase().includes('search') ||
                    aria.toLowerCase().includes('search') ||
                    id.toLowerCase().includes('search')
                ) {
                    var rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).display !== 'none' && window.getComputedStyle(el).visibility !== 'hidden') {
                        return el;
                    }
                }
            }
            return null;
            """
            element = driver.execute_script(search_js)
            if element:
                return element
        except Exception:
            pass

    return None

last_found_element = None

def random_delay(min_seconds=0.1, max_seconds=0.3):
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)
    return delay

def execute_action(action):
    global last_found_element
    
    try:
        action_type = action.get("action")
        description = action.get("description", action_type.replace("_", " ").title())
        print(f"Executing: {description}")
        
        if action_type == "navigate":
            url = action.get("url")
            driver.get(url)
            WebDriverWait(driver, 5).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            time.sleep(0.5)
            print(f"Navigated to: {url}")
            
            try:
                handle_common_popups()
            except:
                pass
            
        elif action_type == "find_and_click":
            element_properties = action.get("element_properties", {})
            is_search = 'is_search' in element_properties or (
                'placeholder' in element_properties and 'search' in element_properties['placeholder'].lower() or
                'aria-label' in element_properties and 'search' in element_properties['aria-label'].lower()
            )
            
            element = find_element_by_properties(element_properties)
            
            if element:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                random_delay(0.1, 0.2)
                
                try:
                    WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.XPATH, f"//{element.tag_name}[@id='{element.get_attribute('id')}']" if element.get_attribute('id') else ".")))
                except:
                    pass
                
                try:
                    element.click()
                except Exception as e:
                    print(f"Direct click failed: {str(e)}, trying JavaScript click")
                    driver.execute_script("arguments[0].click();", element)
                
                last_found_element = element
                print(f"Found and clicked element: {element_properties}")
            else:
                if is_search:
                    try:
                        search_js = """
                        (function findAndClickSearch() {
                            const searchButtons = [
                                document.querySelector('button[aria-label*="search" i]'),
                                document.querySelector('button.search'),
                                document.querySelector('button[type="submit"]'),
                                document.querySelector('a.search-icon'),
                                document.querySelector('*[id*="search-button"]'),
                                document.querySelector('*[class*="search-button"]')
                            ].filter(el => el !== null);
                            
                            if (searchButtons.length > 0) {
                                searchButtons[0].click();
                                return true;
                            }
                            return false;
                        })();
                        """
                        success = driver.execute_script(search_js)
                        if success:
                            print("Found and clicked search element using JavaScript")
                            random_delay(0.3, 0.6)
                            return False
                    except Exception as e:
                        print(f"JavaScript search interaction failed: {str(e)}")
                
                print(f"Could not find element with properties: {element_properties}")
                driver.save_screenshot("element_not_found.png")
                
        elif action_type == "type":
            text = action.get("text")
            if action.get("use_previous_element") and last_found_element:
                element = last_found_element
            elif "element_properties" in action:
                element = find_element_by_properties(action.get("element_properties"))
                last_found_element = element
            else:
                print("No element specified for typing")
                return
                
            if element:
                WebDriverWait(driver, 5).until(EC.visibility_of(element))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                random_delay(0.1, 0.2)
                
                try:
                    element.clear()
                except Exception:
                    element.send_keys(Keys.CONTROL + "a")
                    element.send_keys(Keys.DELETE)
                
                for char in text:
                    element.send_keys(char)
                    random_delay(0.01, 0.05)
                print(f"Typed '{text}' into element")
            else:
                print("Element for typing not found")
                
        elif action_type == "press_enter":
            if action.get("use_previous_element") and last_found_element:
                element = last_found_element
            elif "element_properties" in action:
                element = find_element_by_properties(action.get("element_properties"))
                last_found_element = element
            else:
                print("No element specified for pressing Enter")
                return
                
            if element:
                element.send_keys(Keys.RETURN)
                print("Pressed Enter on element")
            else:
                print("Element for pressing Enter not found")
                
        elif action_type == "scroll":
            direction = action.get("direction", "down")
            amount = action.get("amount", 500)
            
            if direction == "down":
                driver.execute_script(f"window.scrollBy(0, {amount});")
                print(f"Scrolled down: {amount}px")
            elif direction == "up":
                driver.execute_script(f"window.scrollBy(0, -{amount});")
                print(f"Scrolled up: {amount}px")
            elif direction == "to_top":
                driver.execute_script("window.scrollTo(0, 0);")
                print("Scrolled to top of page")
            elif direction == "to_bottom":
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                print("Scrolled to bottom of page")
            else:
                driver.execute_script(f"window.scrollBy(0, {amount});")
                print(f"Scrolled: {amount}px")
                
        elif action_type == "scroll_to_element":
            element_properties = action.get("element_properties", {})
            element = find_element_by_properties(element_properties)
            
            if element:
                alignment = action.get("alignment", "center")
                driver.execute_script(f"arguments[0].scrollIntoView({{block: '{alignment}'}});", element)
                print(f"Scrolled to element: {element_properties}")
                last_found_element = element
            else:
                print("Element to scroll to not found")
                
        elif action_type == "new_tab":
            url = action.get("url", "about:blank")
            driver.execute_script(f"window.open('{url}');")
            driver.switch_to.window(driver.window_handles[-1])
            print(f"Opened new tab with URL: {url}")
            if url != "about:blank":
                WebDriverWait(driver, 5).until(
                    lambda d: d.execute_script('return document.readyState') == 'complete'
                )
                try:
                    handle_common_popups()
                except:
                    pass
                    
        elif action_type == "close_tab":
            if len(driver.window_handles) > 1:
                current_tab = driver.current_window_handle
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                print("Closed current tab and switched to first tab")
            else:
                print("Cannot close tab - only one tab remains open")
                
        elif action_type == "switch_tab":
            tab_index = action.get("index", 0)
            tab_url = action.get("url", "")
            
            if tab_url:
                for handle in driver.window_handles:
                    driver.switch_to.window(handle)
                    if tab_url in driver.current_url:
                        print(f"Switched to tab with URL containing: {tab_url}")
                        break
                else:
                    print(f"No tab found with URL containing: {tab_url}")
            else:
                if 0 <= tab_index < len(driver.window_handles):
                    driver.switch_to.window(driver.window_handles[tab_index])
                    print(f"Switched to tab at index {tab_index}")
                else:
                    print(f"Tab index {tab_index} out of range")
        
        elif action_type == "refresh_page":
            driver.refresh()
            WebDriverWait(driver, 5).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            print("Page refreshed")
            
        elif action_type == "go_back":
            driver.back()
            WebDriverWait(driver, 5).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            print("Navigated back")
            
        elif action_type == "go_forward":
            driver.forward()
            WebDriverWait(driver, 5).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            print("Navigated forward")
            
        elif action_type == "wait":
            seconds = action.get("seconds", 0.5)
            time.sleep(seconds)
            print(f"Waited: {seconds} seconds")
            
        elif action_type == "complete":
            print("Task marked as complete")
            return True
            
        else:
            print(f"Unknown action: {action_type}")
        
        random_delay(0.2, 0.5)
        return False
        
    except Exception as e:
        print(f"Action execution failed: {str(e)}")
        driver.save_screenshot(f"error_{action_type}.png")
        return False

def handle_common_popups():
    common_button_texts = ['Accept', 'Accept All', 'I Agree', 'Accept Cookies', 'OK', 'Got it', 'Agree', 'Close']
    
    for text in common_button_texts:
        try:
            buttons = driver.find_elements(By.XPATH, f"//*[contains(text(), '{text}')]")
            for button in buttons:
                if button.is_displayed():
                    button.click()
                    print(f"Closed popup with button: {text}")
                    return
        except:
            continue
    
    common_close_selectors = [
        "//button[@aria-label='Close']",
        "//button[contains(@class, 'close')]",
        "//div[contains(@class, 'popup')]//button",
        "//div[contains(@class, 'cookie')]//button",
        "//div[contains(@class, 'consent')]//button"
    ]
    
    for selector in common_close_selectors:
        try:
            buttons = driver.find_elements(By.XPATH, selector)
            for button in buttons:
                if button.is_displayed():
                    button.click()
                    print(f"Closed popup with selector: {selector}")
                    return
        except:
            continue

def get_browser_state():
    try:
        return {
            "url": driver.current_url,
            "title": driver.title,
            "domain": driver.current_url.split("//")[-1].split("/")[0],
            "tab_index": get_current_tab_index(),
            "tab_count": len(driver.window_handles)
        }
    except:
        return {"url": "", "title": "", "domain": "", "tab_index": 0, "tab_count": 1}

def get_current_tab_index():
    try:
        current_window = driver.current_window_handle
        return driver.window_handles.index(current_window)
    except:
        return 0

def main():
    global conversation_history
    print("Web Automation Agent started.")
    
    current_browser_state = get_browser_state()
    
    user_instruction = input("Enter your instruction: ")
    
    while user_instruction.lower() not in ["exit", "quit", "stop"]:
        print("Processing instruction...")
        print(f"Task: {user_instruction}")
        
        current_browser_state = get_browser_state()
        print(f"Current browser state: {current_browser_state['url']}")
        
        if not any(msg.get("content") == user_instruction for msg in conversation_history if msg.get("role") == "user"):
            augmented_instruction = f"{user_instruction} (Current page: {current_browser_state['title']} - {current_browser_state['url']})"
            conversation_history.append({"role": "user", "content": augmented_instruction})
        
        llm_response = send_command_to_llm(user_instruction)
        try:
            print(f"Planning actions: {str(llm_response)[:100]}...")
            
            if isinstance(llm_response, list):
                actions = llm_response
            elif isinstance(llm_response, dict) and "actions" in llm_response:
                actions = llm_response["actions"]
            elif isinstance(llm_response, dict):
                actions = [llm_response]
            else:
                raise ValueError(f"Unexpected response format: {type(llm_response)}")
            
            if actions and actions[0].get("action") == "navigate":
                target_url = actions[0].get("url", "")
                current_domain = current_browser_state.get("domain", "")
                target_domain = target_url.split("//")[-1].split("/")[0] if "//" in target_url else ""
                
                if current_domain and target_domain and current_domain == target_domain:
                    print(f"Already on {current_domain}. Skipping navigation.")
                    actions = actions[1:]
                
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Error processing LLM response: {str(e)}")
            print("Please try again with a different instruction.")
            user_instruction = input("Enter your next instruction (or type 'exit' to quit): ")
            continue
        
        if not actions:
            print("No actions to execute. Please try a different instruction.")
            user_instruction = input("Enter your next instruction (or type 'exit' to quit): ")
            continue
            
        print(f"{len(actions)} initial actions identified.")
        
        for action in actions:
            if execute_action(action):
                break
        
        max_iterations = 10
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            try:
                html_content = preprocess_html(driver.page_source)
                print(f"\nIteration {iteration}: Analyzing page and determining next steps...")
                
                current_browser_state = get_browser_state()
                continuation_prompt = f"Continue executing the instruction: '{user_instruction}'. Current page: {current_browser_state['title']} - {current_browser_state['url']}. What's the next step?"
                llm_response = send_command_to_llm(continuation_prompt, html_content)
                
                print(f"Next actions planned: {str(llm_response)[:100]}...")
                
                try:
                    if isinstance(llm_response, list):
                        next_actions = llm_response
                    elif isinstance(llm_response, dict) and "actions" in llm_response:
                        next_actions = llm_response["actions"]
                    elif isinstance(llm_response, dict):
                        next_actions = [llm_response]
                    else:
                        raise ValueError(f"Unexpected response format: {type(llm_response)}")
                    
                    if next_actions and next_actions[0].get("action") == "navigate":
                        target_url = next_actions[0].get("url", "")
                        current_domain = current_browser_state.get("domain", "")
                        target_domain = target_url.split("//")[-1].split("/")[0] if "//" in target_url else ""
                        
                        if current_domain and target_domain and current_domain == target_domain:
                            print(f"Already on {current_domain}. Skipping navigation.")
                            next_actions = next_actions[1:]
                    
                    if not next_actions:
                        print("Task completed successfully!")
                        break
                    
                    print(f"Executing {len(next_actions)} actions for iteration {iteration}...")
                    
                    task_complete = False
                    for action in next_actions:
                        if execute_action(action):
                            task_complete = True
                            break
                    
                    if task_complete:
                        print("Task completed successfully!")
                        break
                        
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"Error processing LLM response: {str(e)}")
                    break
                    
            except Exception as e:
                print(f"Error occurred during execution: {str(e)}")
                break
        
        if iteration >= max_iterations:
            print("Maximum number of iterations reached. Task may be incomplete.")
        
        current_browser_state = get_browser_state()
        
        completion_summary = f"Completed task: {user_instruction}. Current page: {current_browser_state['title']} - {current_browser_state['url']}"
        conversation_history.append({"role": "assistant", "content": completion_summary})
        
        if len(conversation_history) > 4:
            print("\nMemory summary (last 3 tasks):")
            for i in range(len(conversation_history)-6, len(conversation_history), 2):
                if i >= 0:
                    print(f"- {conversation_history[i].get('content', '')[:50]}...")
        
        if len(conversation_history) > 20:
            conversation_history = conversation_history[:2] + conversation_history[-18:]
        
        user_instruction = input(f"Task finished. Browser is at: {current_browser_state['url']}\nEnter your next instruction (or type 'exit' to quit): ")
    
    print("Execution finished. Browser will remain open until you close it.")
    print("Press Ctrl+C in the terminal when you want to exit the program.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nProgram terminated by user. Closing browser...")
        driver.quit()

if __name__ == "__main__":
    main()
