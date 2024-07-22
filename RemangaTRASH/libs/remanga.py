import asyncio
import json
import os
from asyncio import set_event_loop_policy, WindowsSelectorEventLoopPolicy
from curl_cffi.requests import Session, Response, AsyncSession
from loguru import logger
from libs.http_conn import AsyncHTTP, SyncHTTP  # type: ignore
from typing import Optional, Dict


class ReManga:
    BASE_URL: str = "https://api.remanga.org/api"
    BASE_PATHS: dict = {
        "login": "/users/login/",
        "views": "/activity/views/",
        "inventory": "/inventory/{}",
        "catalog": "/search/catalog",
        "chapters": "/titles/chapters",
        "current": "/v2/users/current",
        "bookmarks": "/users/{}/bookmarks",
        "id": "users/current/",
        "merge_cards": "/inventory/{}/cards/merge/",
        "count_bookmarks": "/users/{}/user_bookmarks",
    }
    SITE_URL: str = "https://remanga.org"
    SITE_PATHS: dict = {
        "node": "/node-api/cookie/",
        "manga_page": "/_next/data/0WMsTVhcJNvltEilcpQjj/ru/manga/{}.json",
    }
    DATA_DIR = "data"
    CACHE_PATH = "data/{}_cache.json"

    set_event_loop_policy(WindowsSelectorEventLoopPolicy())

    def __init__(
        self,
        username: str = None,
        password: str = None,
        token: str = None,
        auto_craft: str = None,
    ):
        self.username = username
        self.password = password
        self.token = token
        self.auto_craft = auto_craft
        self.headers: dict = {
            "user-agent": "okhttp",
            "refer": self.SITE_URL,
            "content-type": "application/json",
            "origin": self.SITE_URL,
            "agesubmitted": "true",
            "x-nextjs-data": "1",
        }
        self.user_info = {}
        self.page = 0
        self.ignore_list = {}
        self.viewed_chapters = []
        self.need_to_view_title = {}
        self.need_to_view_chapters = {}
        self.sync_session = SyncHTTP(Session())
        self.async_session = AsyncHTTP(AsyncSession())
        self.__load_cache() or self.__login(self.username, self.password, self.token)
        self.__update_manga_page_path()
        logger.success(
            f'<{self.username or self.user_info.get("username", "Ошибка авторизации")}: Successful login>'
        )

    def __login(
        self, username: str = None, password: str = None, token: str = None
    ) -> None:
        cookie_jar = ["agesubmitted=true;"]

        def unpack_cookie(response: Optional[Response]):
            if not isinstance(response, Response):
                logger.error(
                    "Ожидался объект Response, получен {}".format(type(response))
                )
            return None
            if response is None:
                logger.error(
                    "Error unpacking cookie: Response is None, cannot unpack cookie."
                )
                return None  # или другое подходящее значение по умолчанию
            set_cookie = response.headers.get("set-cookie")
            if set_cookie is None:
                logger.error("Set-Cookie header is not present in the response.")
                return None  # или другое подходящее значение по умолчанию
            return set_cookie.split(";")[0].split("=")

        try:
            node_url = self.BASE_URL + self.BASE_PATHS["login"]

            data = json.dumps(
                [
                    {
                        "key": "serverUser",
                        "value": ".Apostol.",
                        "options": {"httpOnly": True},
                    }
                ]
            )

            data = json.dumps(
                {"key": "serverUser", "value": username, "options": {"httpOnly": True}}
            )

            #######################################https://api.remanga.org/api/users/login/
            logger.debug(
                f"Отправка POST запроса к {node_url} с данными:{node_url},{self.headers},{data}"
            )

            response = self.sync_session.req(
                "POST", url=node_url, headers=self.headers, data=data
            )
            logger.debug(f"Полученный ответ: {response}")
            #######################################

            response = self.sync_session.req(
                "POST", url=node_url, headers=self.headers, data=data
            )

            if response is None:
                logger.error("Не удалось получить ответ от сервера")
            else:
                if response.status_code == 200:
                    # Обработка успешного ответа
                    pass
                else:
                    # Обработка ошибочных ситуаций
                    logger.error(f"Ошибка: {response.status_code}")

            cookie_parts = unpack_cookie(response)
            if cookie_parts is None:
                logger.error("Ответ сервера None, cookie не может быть извлечен.")
                return  # Выход из функции или обработка ошибки

            cookie_jar.append(f"{cookie_parts[0]}={cookie_parts[1]}")
            cookie_jar.append(f"user={cookie_parts[1]}")

            access_token = self.get_access_token()
            cookie_jar.append(f"token={access_token};")
            self.headers["token"] = access_token
            self.headers["authorization"] = f"bearer {access_token}"

            self.headers["cookie"] = " ".join(cookie_jar)

        except ValueError as e:
            logger.error(f"Error unpacking cookie: {e}")

        def get_cookie_server_user(user_meta):
            node_url = self.SITE_URL + self.SITE_PATHS.get("node")
            data = [
                {"key": "serverUser", "value": user_meta, "options": {"httpOnly": True}}
            ]
            response = self.sync_session.req(
                "POST", url=node_url, headers=self.headers, data=data
            )
            cookie = unpack_cookie(response)
            cookie_jar.append(f"{cookie[0]}={cookie[1]}")
            cookie_jar.append(f"user={cookie[1]}")
            response = self.sync_session.req(
                "POST", url=node_url, headers=self.headers, data=data
            )

        def get_cookie_server_token(user_token: str):
            node_url = self.SITE_URL + self.SITE_PATHS.get("node")
            data = [
                {
                    "key": "serverToken",
                    "value": user_token,
                    "options": {"httpOnly": True},
                }
            ]
            response = self.sync_session.req(
                "POST", url=node_url, headers=self.headers, data=data
            )

            # Добавляем проверку, чтобы убедиться, что response не None
            if response is None:
                logger.error("Не удалось получить ответ от сервера")
                return None

            # После проверки, что ответ не None, можно попытаться извлечь куки
            cookie = unpack_cookie(response)
            if cookie is None:
                logger.error("Не удалось извлечь куки из ответа")
                return None

            cookie_jar.append(f"{cookie[0]}={cookie[1]};")

        def get_access_token():
            url = self.BASE_URL + self.BASE_PATHS["login"]
            payload = {
                "user": self.username,
                "password": self.password,
                "g-recaptcha-response": "WITHOUT_TOKEN",
            }
            response = self.sync_session.req(
                "POST", url=url, headers=self.headers, data=payload
            )
            try:
                content = response.json()  # Пытаемся декодировать JSON
            except ValueError:
                logger.error("Не удалось декодировать JSON из ответа")
                return None

            # Проверяем, является ли содержимое словарём
            if not isinstance(content, dict):
                logger.error("Ответ не является словарём")
                return None

            # Теперь безопасно используем .get для доступа к данным
            access_token = content.get("content", {}).get("access_token")
            return access_token

        if (username and password) or token:
            access_token = token or get_access_token()
            cookie_jar.append(f"token={access_token};")
            self.headers["token"] = access_token
            self.headers["authorization"] = f"bearer {access_token}"
            metadata = self.user_info if token else None
            self.user_info = metadata or self.user_info
            self.user_info["token"] = access_token
            get_cookie_server_user(json.dumps(self.user_info))
            get_cookie_server_token(access_token)
            self.headers["cookie"] = " ".join(cookie_jar)
        else:
            raise ValueError("No auth credentials. Please provide information")

    def __update_manga_page_path(self):
        response = self.sync_session.req(
            "GET", self.SITE_URL + self.SITE_PATHS["manga_page"], headers=self.headers
        )
        if response and response.text:
            for i in response.text.split():
                if "_buildManifest.js" in i:
                    new_path = f'/_next/data/{i.split("/")[3]}' + "/ru/manga/{}.json"
                    self.SITE_PATHS["manga_page"] = new_path
                    logger.info(f"Updated manga page path: {new_path}")
            print(self.headers)

    def __get_endpoint_with_user_id(self, endpoint) -> str:
        return self.BASE_PATHS[endpoint].format(self.user_info["id"])

    async def __get_total_count_bookmarks(self) -> int:
        url = self.BASE_URL + self.__get_endpoint_with_user_id("count_bookmarks")
        response = await self.async_session.req("GET", url=url, headers=self.headers)
        count = 0
        if response is not None:
            # Проверяем, что response не None, прежде чем вызывать .json()
            for bookmark_type in response.json().get("content", []):
                count += bookmark_type.get("count", 0)
        else:
            # Если response равен None, обрабатываем этот случай.
            # Например, можно записать в лог ошибку или выбросить исключение.
            logger.error("Не удалось получить ответ от сервера")
        return count

    async def get_user_bookmarks_for_ignore(self) -> dict:
        bookmark_count = await self.__get_total_count_bookmarks()
        url = self.BASE_URL + self.__get_endpoint_with_user_id("bookmarks")
        querystring = {"type": "0", "count": f"{bookmark_count}", "page": "1"}
        response = await self.async_session.req(
            "GET", url=url, headers=self.headers, params=querystring
        )
        if response != None:
            if response.status_code == 200:
                for title in response.json().get("content", []):
                    title_id = title.get("title", {}).get("id", "")
                    title_dir = title.get("title", {}).get("dir", "")
                    self.ignore_list[title_id] = title_dir
                else:
                    logger.error("Failed to fetch bookmarks.")
                return self.ignore_list
        else:
            logger.error("Failed to fetch bookmarks.")

        return self.ignore_list

    def __get_endpoint_with_user_id(self, endpoint) -> str:
        return self.BASE_PATHS[endpoint].format(self.user_info.get("id", ""))

    async def __unpack_catalog(self, content: list) -> None:
        for title in content:
            title_id = title.get("id")
            if (
                title_id not in self.ignore_list
                and title_id not in self.need_to_view_title
            ):
                self.need_to_view_title[title_id] = {
                    "dir": title["dir"],
                    "name": title["main_name"],
                }

    @staticmethod
    def __filter_cards(cards) -> dict:
        filtered_cards = {}
        for card in cards:
            rank = card["rank"]
            title_dir = card["title_dir"]
            card_id = card["id"]
            if rank not in filtered_cards:
                filtered_cards[rank] = []
            title_dir_found = False
            for item in filtered_cards[rank]:
                if title_dir in item:
                    item[title_dir].append(card_id)
                    title_dir_found = True
                    break
            if not title_dir_found:
                filtered_cards[rank].append({title_dir: [card_id]})
        return filtered_cards

    async def get_all_cards(self):
        page = 1
        cards = []
        total_cards = 0
        url = self.BASE_URL + self.__get_endpoint_with_user_id("inventory")
        while True:
            querystring = {"type": "cards", "page": f"{page}"}
            logger.debug(
                f"Отправка GET запроса к {url} с данными:{self.headers},{querystring}"
            )
            response = await self.async_session.req(
                "GET", url=url, headers=self.headers, params=querystring
            )
            data = response.json().get("content", [])
            if data:
                for card in data:
                    card_id = card.get("id")
                    rank = card.get("rank")
                    title_id = (
                        card.get("title", {}).get("id") if card.get("title") else None
                    )
                    title_dir = (
                        card.get("title", {}).get("dir") if card.get("title") else None
                    )
                    cards.append(
                        {
                            "rank": rank,
                            "id": card_id,
                            "title_id": title_id,
                            "title_dir": title_dir,
                        }
                    )
                total_cards += 1
                page += 1
            else:
                break
        return cards

    async def merge_cards(self, cards: list[int] = None):
        payload = {"cards": cards}
        url = self.BASE_URL + self.__get_endpoint_with_user_id("merge_cards")
        await self.async_session.req(
            "POST", url=url, headers=self.headers, data=payload
        )
        logger.success(f'{self.username or self.user_info["username"]}: Cards merged!')

    async def auto_craft_cards(self, rank: str = "rank_f"):
        cards = self.__filter_cards(await self.get_all_cards())
        for titles in cards[rank]:
            for title_dir, card_ids in titles.items():
                if len(card_ids) >= 2:
                    for i in range(0, len(card_ids), 2):
                        if i + 1 < len(card_ids):
                            await self.merge_cards(card_ids[i : i + 2])

    async def get_catalog(self, order_by: str = "id") -> dict:
        api_endpoint = self.BASE_PATHS["catalog"]
        url = self.BASE_URL + api_endpoint
        querystring = {
            "content": "manga",
            "count": "3000",
            "ordering": order_by,
            "page": f"{self.page}",
        }
        response = await self.async_session.req(
            "GET", url=url, headers=self.headers, params=querystring
        )
        await self.__unpack_catalog(response.json().get("content", []))
        return self.need_to_view_title

    async def __farm_view(self) -> None:
        async def view_chapter(chapter_i: tuple, m_dir: dict) -> None:
            url = self.BASE_URL + self.BASE_PATHS.get("views")
            payload = {"chapter": int(chapter_i[0]), "page": -1}
            await self.async_session.req(
                "POST", url=url, headers=self.headers, data=payload
            )
            text = (
                f'<{self.username or self.user_info.get("username")}'
                f' Viewed: Manga: {m_dir.get("name")}, Chapter: {chapter_i[1]}>'
            )
            logger.info(text)
            self.viewed_chapters.append(chapter_i[0])

        async def get_manga_branch(m_dir: dict) -> None:
            url = self.SITE_URL + self.SITE_PATHS.get("manga_page").format(
                m_dir.get("dir")
            )
            querystring = {
                "content": "manga",
                "title": m_dir.get("dir"),
                "p": "chapters",
            }
            response = await self.async_session.req(
                "GET", url=url, headers=self.headers, params=querystring
            )
            if response:
                data = response.json().get("pageProps", {}).get("fallbackData", {})
                branches = data.get("content", {}).get("branches", [])
                current_reading = data.get("content", {}).get("current_reading", {})
                if branches:
                    branch: int = branches[0].get("id")
                    chapter = (
                        float(current_reading.get("chapter"))
                        if current_reading
                        else 0.0
                    )
                    await get_manga_chapters(branch, m_dir, chapter)

        async def get_manga_chapters(branch: int, m_dir, viewed_chapter: float):
            url = self.BASE_URL + self.BASE_PATHS.get("chapters")
            querystring = {"branch_id": f"{branch}", "user_data": "0"}
            response = await self.async_session.req(
                "GET", url=url, headers=self.headers, params=querystring
            )
            if response:
                chapters = []
                for chapter in response.json().get("content", [])[::-1]:
                    if chapter.get("is_paid") is True:
                        continue
                    try:
                        if float(chapter.get("chapter", 0)) < viewed_chapter:
                            continue
                    except ValueError:
                        if (
                            float(
                                chapter.get("chapter").replace("-", ".").split(".")[0]
                            )
                            < viewed_chapter
                        ):
                            continue
                    if chapter.get("id") not in self.viewed_chapters:
                        chapters.append((chapter.get("id"), chapter.get("chapter")))
                await asyncio.gather(
                    *[view_chapter(chapter, m_dir) for chapter in chapters]
                )

        tasks = []
        for manga_dir in self.need_to_view_title.values():
            tasks.append(get_manga_branch(manga_dir))
        await asyncio.gather(*tasks)

    def __load_cache(self):
        path = (
            self.CACHE_PATH.format(self.username)
            if self.username
            else self.CACHE_PATH.format(self.token)
        )
        if os.path.exists(path):
            with open(path, "r", encoding="windows-1251") as file:
                data = json.load(file)
                self.page = data.get("page")
                self.token = data.get("token")
                self.headers = data.get("headers")
                self.username = data.get("username")
                self.password = data.get("password")
                self.user_info = data.get("user_info")
                self.viewed_chapters = data.get("viewed")
            return True

    async def __save_viewed(self):
        if not os.path.exists(self.DATA_DIR):
            os.mkdir(self.DATA_DIR)
        path = (
            self.CACHE_PATH.format(self.username)
            if self.username
            else self.CACHE_PATH.format(self.user_info["username"])
        )
        with open(path, "w", encoding="utf-8") as file:
            json.dump(data_to_save, file, ensure_ascii=False)  # type: ignore

    async def time_to_fun(self):
        await self.get_user_bookmarks_for_ignore()
        while True:
            self.page += 1
            await self.get_catalog()
            await self.__farm_view()
            if self.auto_craft:
                await self.auto_craft_cards()
            logger.success(
                f'<{self.username or self.user_info.get("username")}: TIMEBREAK 20 SEC>'
            )
            await asyncio.sleep(20)


# Запуск асинхронной функции
if __name__ == "__main__":
    username = "your_username"  # Замените на ваше имя пользователя
    password = "your_password"  # Замените на ваш пароль
    token = None  # Укажите токен, если есть
    auto_craft = None  # Укажите, если необходимо авто-обработка

    remanga_instance = ReManga(
        username=username, password=password, token=token, auto_craft=auto_craft
    )

    try:
        asyncio.run(remanga_instance.time_to_fun())
    except KeyboardInterrupt:
        logger.info("Программа остановлена пользователем.")
    except Exception as e:
        logger.error(f"Произошла ошибка: {e}")
