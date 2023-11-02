from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from cachetools import TTLCache
import urllib.parse
import aiohttp
import os
import uuid
import asyncio

app = FastAPI()

# 캐시 설정: 최대 100개 항목, 각 항목은 3600초(1시간) 동안 유지
cache = TTLCache(maxsize=100, ttl=3600)

# 이미지 저장 경로 지정
image_storage_path = "images"
os.makedirs(image_storage_path, exist_ok=True)

async def download_and_save_image(img_url: str, file_path: str, session: aiohttp.ClientSession):
    try:
        async with session.get(img_url) as resp:
            if resp.status == 200:
                with open(file_path, 'wb') as f:
                    f.write(await resp.read())
                return file_path
    except Exception as e:
        print(f"Error downloading {img_url}: {e}")
    return None

@app.get("/images/{filename}")
async def get_image(filename: str):
    file_path = os.path.join(image_storage_path, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return JSONResponse(status_code=404, content={"message": "Image not found"})

@app.get("/scrap")
async def scrap(query: str):
    options = ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-extensions')
    options.add_experimental_option('prefs', {'profile.managed_default_content_settings.images': 2})

    query_encoded = urllib.parse.quote(query)

    if query_encoded in cache:
        return JSONResponse(content=cache[query_encoded])

    url = f'https://search.danawa.com/dsearch.php?query={query_encoded}&originalQuery={query_encoded}&checkedInfo=N&volumeType=vmvs&page=1&limit=40'

    results = []
    async with aiohttp.ClientSession() as session:
        with webdriver.Chrome(options=options) as driver:
            driver.get(url)
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'li.prod_item')))
            soup = BeautifulSoup(driver.page_source, "html.parser")
            product_li_tags = soup.select('li.prod_item')

            download_tasks = []
            for li in product_li_tags:
                name_element = li.select_one('p.prod_name a')
                img_element = li.select_one('div.thumb_image a img')

                if name_element is None or img_element is None:
                    continue

                name = name_element.text.strip()
                img_link = img_element.get('data-src') or img_element.get('src')
                if img_link.startswith("//"):
                    img_link = "https:" + img_link
                img_link = img_link.split('?')[0]

                img_filename = str(uuid.uuid4()) + ".jpg"
                img_path = os.path.join(image_storage_path, img_filename)

                task = asyncio.create_task(download_and_save_image(img_link, img_path, session))
                download_tasks.append(task)
                results.append({"name": name, "img_path": img_path})

            # 이미지 다운로드
            downloaded_images = await asyncio.gather(*download_tasks)

            for result, img_file in zip(results, downloaded_images):
                if img_file:
                    result["img_link"] = f"http://218.144.111.204:2222/images/{os.path.basename(img_file)}"
                else:
                    result["img_link"] = None

    cache[query_encoded] = results
    return JSONResponse(content=results)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
