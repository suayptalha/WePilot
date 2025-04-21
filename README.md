# WePlot

The WePlot is a web automation agent that executes user instructions by interacting with websites. It uses Selenium for browser automation, BeautifulSoup for HTML parsing, and Hugging Face's InferenceClient to generate actionable commands based on user input.

## Features

- **Browser Automation:**  
  Configures and launches a Selenium-controlled Chrome browser with settings to minimize detection by websites.

- **Dynamic Element Detection:**  
  Uses BeautifulSoup to parse HTML and identify interactive elements such as search boxes, buttons, and links based on their attributes.

- **LLM Integration:**  
  Sends user commands to a language model via Hugging Face's InferenceClient. The model returns a JSON response with actions to perform (e.g., navigate, click, type).

- **Adaptive Interaction:**  
  Continuously refines its actions by analyzing the page content in subsequent iterations until the task is complete.

- **Popup Handling:**  
  Automatically detects and closes common pop-ups to maintain smooth automation.

- **Error Handling:**  
  Implements error capturing (including taking screenshots) when actions fail or elements are not found.

## Requirements

- Python 3.x
- `beautifulsoup4>=4.9.3`
- `selenium>=4.0.0`
- `huggingface_hub>=0.10.0`
- `pyautogui>=0.9.50`

## Installation Instructions
To set up the WePilot project, follow these steps:

1. Clone the repository:
   ```
   git clone https://github.com/suayptalha/WePilot.git
   ```

2. Navigate to the project directory:
   ```
   cd WePilot
   ```

3. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Ensure that Google Chrome is installed and that the appropriate [ChromeDriver](https://sites.google.com/chromium.org/driver/) is available in your system PATH.

## Usage

1. Run the script from your terminal:
   ```sh
   python main.py
   ```
2. When prompted, enter your web instruction in the terminal.

The script will process your input, generate a series of actions using the LLM, and execute these actions in the browser to navigate and interact with the target website.

## Notes

- The script continuously monitors and analyzes the page to determine the next best action based on changes in the web page.
- For advanced customization or troubleshooting, refer to the source code and modify element detection logic, popup handling, or LLM response processing as needed.
