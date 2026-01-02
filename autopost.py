from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os
import requests
from bs4 import BeautifulSoup
import time
import re

# --- CONFIGURATION ---
WP_LOGIN_URL = os.environ.get('WP_URL')
WP_USERNAME = os.environ.get('WP_USERNAME')
WP_PASSWORD = os.environ.get('WP_PASSWORD')

SOURCE_URL = "https://toonworld4all.me/"

if not WP_LOGIN_URL or not WP_USERNAME or not WP_PASSWORD:
    raise ValueError("Error: Secrets are missing!.")

# --- SETUP CHROME OPTIONS ---
chrome_options = Options()
chrome_options.add_argument("--headless") # Run in background
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--window-size=1920,1080")
chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

def parse_title(source_title):
    pattern = r"(.*?)\s(Season\s\d+)\s(Multi Audio\s\[.*?\])"
    match = re.search(pattern, source_title, re.IGNORECASE)
    if match:
        return f"{match.group(1).strip()} ({match.group(2).strip()})", match.group(3).strip()
    return source_title, ""

def run_automation():
    # 1. SCRAPE DATA (We still use requests for scraping the source)
    print("Scraping source...")
    r = requests.get(SOURCE_URL, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(r.content, 'html.parser')
    
    # Adjust selector to match the first post on toonworld
    article = soup.find('article') 
    if not article:
        print("No articles found.")
        return

    source_title_text = article.find('h2').text.strip()
    post_link = article.find('a')['href']
    
    final_title, subtitle = parse_title(source_title_text)
    print(f"Found: {final_title}")

    # Scrape inner content
    post_soup = BeautifulSoup(requests.get(post_link, headers={'User-Agent': 'Mozilla/5.0'}).content, 'html.parser')
    content_area = post_soup.find('div', class_='entry-content')
    img_tag = content_area.find('img')
    src_img_url = img_tag['src'] if img_tag else ""
    raw_text = content_area.get_text()

    def get_line(keyword):
        match = re.search(f"{keyword}.*", raw_text, re.IGNORECASE)
        return match.group(0) if match else f"{keyword} N/A"

    # Construct HTML Content
    html_content = f"""
    [toggle title="Info" state="open"]
    <img class="alignnone size-medium" src="{src_img_url}" width="592" height="841" />
    {get_line('Season:')}
    {get_line('Genre:')}
    {get_line('Network:')}
    {get_line('Org. run:')}
    {get_line('Running time:')}
    {get_line('Language:')}
    {get_line('Quality:')}
    [/toggle]
    """

    # 2. START BROWSER AUTOMATION
    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 20)

    try:
        print("Logging into WordPress...")
        driver.get(WP_LOGIN_URL)
        wait.until(EC.presence_of_element_located((By.ID, "user_login"))).send_keys(WP_USERNAME)
        driver.find_element(By.ID, "user_pass").send_keys(WP_PASSWORD)
        driver.find_element(By.ID, "wp-submit").click()
        
        # Check if login worked
        try:
            wait.until(EC.presence_of_element_located((By.ID, "adminmenu")))
        except:
            print("Login failed or timed out.")
            return

        # 3. CHECK DUPLICATES
        driver.get(f"{WP_LOGIN_URL.replace('wp-login.php', 'wp-admin/edit.php')}")
        search_box = wait.until(EC.presence_of_element_located((By.ID, "post-search-input")))
        search_box.send_keys(final_title)
        driver.find_element(By.ID, "search-submit").click()
        
        if "No posts found" not in driver.page_source and final_title in driver.page_source:
            print("Post already exists. Skipping.")
            return

        # 4. CREATE POST
        print("Creating new post...")
        driver.get(f"{WP_LOGIN_URL.replace('wp-login.php', 'wp-admin/post-new.php')}")
        
        # We use Javascript to set values because it's faster/stabler than typing
        
        # Set Title
        title_field = wait.until(EC.presence_of_element_located((By.NAME, "post_title")))
        driver.execute_script("arguments[0].value = arguments[1];", title_field, final_title)
        
        # Set Content (Switch to Text/HTML tab first to ensure raw HTML is pasted)
        try:
            # Click "Text" tab if using Classic Editor or TinyMCE
            driver.find_element(By.ID, "content-html").click() 
            content_field = driver.find_element(By.ID, "content")
            driver.execute_script("arguments[0].value = arguments[1];", content_field, html_content)
        except:
            # Fallback for Gutenberg (Block Editor) - Gutenberg is HARD to automate. 
            # Installing "Classic Editor" plugin makes this script 100x more reliable.
            print("Could not find standard content box. Ensure Classic Editor plugin is active.")

        # 5. SET CUSTOM FIELDS (Jannah Subtitle)
        # You might need to find the specific ID using Inspect Element on your site
        # Example for Jannah Subtitle usually:
        try:
            # Scroll down to ensure elements are loaded
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            # Subtitle
            # Note: Replace 'jannah_subtitle_id' with the real ID if this fails.
            # Often it is named 'post_subtitle' or similar in Jannah options.
            subtitle_input = driver.find_elements(By.CSS_SELECTOR, "input[name*='subtitle']")
            if subtitle_input:
                subtitle_input[0].send_keys(subtitle)

            # Taqyeem Rating
            # Look for an input related to taqyeem score
            score_input = driver.find_elements(By.CSS_SELECTOR, "input[name*='taq_review_score']") 
            if score_input:
                score_input[0].send_keys("8.5") # Or whatever logic you want

        except Exception as e:
            print(f"Warning: Could not set custom fields. {e}")

        # 6. SET FEATURED IMAGE (Using FIFU Plugin)
        # If you installed 'Featured Image from URL' plugin, there is an input box for it.
        try:
            fifu_input = driver.find_element(By.ID, "fifu_input_url") # Standard ID for FIFU plugin
            fifu_input.send_keys(src_img_url)
            # Click the preview/save button for FIFU if exists
        except:
            print("FIFU input not found. Install 'Featured Image from URL' plugin.")

        # 7. PUBLISH
        print("Publishing...")
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)
        
        publish_btn = driver.find_element(By.ID, "publish")
        driver.execute_script("arguments[0].click();", publish_btn)
        
        time.sleep(5) # Wait for publish
        print("Done!")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_automation()
