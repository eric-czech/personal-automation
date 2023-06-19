import json
import logging
import re
import time
from typing import Any
from urllib.parse import quote

import fire
import gcsfs
import pandas as pd
import requests  # type: ignore[import]
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

logger = logging.getLogger()

LOOKER_REPORT_URL = "https://lookerstudio.google.com/reporting/50b3abce-f84d-40f2-b47d-1d03d8c48f71/page/5urUD"


class HotelPrices:
    def get_prices(
        self, start_date: str, stop_date: str, sleep_secs: int = 5
    ) -> list[dict[str, Any]]:
        """Scrape Seven Stars hotel prices for a given time range

        Example URL: https://www.reservhotel.com/providenciales-turks-and-caicos-islands/seven-stars-resort/booking-engine/ibe5.main?hotel=10208&date_format=MM%2FDD%2FYYYY&aDate=04%2F01%2F2024&dDate=04%2F08%2F2024&airport=&adults=2&child=0&rooms=1&fareclass=1

        """
        url_format = "https://www.reservhotel.com/providenciales-turks-and-caicos-islands/seven-stars-resort/booking-engine/ibe5.main?hotel=10208&date_format=MM%2FDD%2FYYYY&aDate={start_date}&dDate={stop_date}&airport=&adults=2&child=0&rooms=1&fareclass=1"  # noqa: E501
        url = url_format.format(
            start_date=quote(start_date, safe=""), stop_date=quote(stop_date, safe="")
        )
        logger.info(f"Processing url '{url}'")
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36"  # noqa: E501
        options = Options()
        options.add_argument(f"user-agent={user_agent}")
        options.add_argument("--headless")
        driver = webdriver.Chrome(options=options)
        driver.get(url)
        time.sleep(sleep_secs)
        rows = driver.find_elements(By.CSS_SELECTOR, "div.row.room-row-list")
        res = []
        for row in rows:
            try:
                room_name_elems = row.find_elements(
                    By.CSS_SELECTOR, "h4[class*='hotel-heading']"
                )
                if len(room_name_elems) == 0:
                    continue
                room_name = None
                for e in room_name_elems:
                    if len(v := e.text.strip()) > 0:
                        room_name = v
                        break
                if room_name is None:
                    continue
                room_price_elems = row.find_elements(
                    By.CSS_SELECTOR, "[class*='price']"
                )
                room_prices = []
                for e in room_price_elems:
                    try:
                        text = e.text.strip()
                        if (
                            len(text) > 0
                            and len(p := re.findall("([0-9.,]+)", text)) == 1
                        ):
                            room_prices.append(float(p[0].replace(",", "")))
                    except Exception:
                        pass
                if len(room_prices) == 0:
                    continue
                res.append(
                    dict(room_name=room_name, room_prices=sorted(set(room_prices)))
                )
            except Exception as e:
                logger.exception(e)
                try:
                    row_html = row.get_attribute("innerHTML")
                    logger.error(f"Failed processing row with html {row_html}")
                except Exception:
                    pass
        logger.info(f"Returning {len(res)} prices for url '{url}': {res}")
        return res

    def collect(
        self,
        output_path: str,
        start_date: str = "04/01/2024",
        stop_date: str = "04/08/2024",
    ) -> None:
        prices = self.get_prices(start_date=start_date, stop_date=stop_date)
        timestamp = int(time.time())
        results = dict(
            prices=prices,
            start_date=start_date,
            stop_date=stop_date,
            output_path=output_path,
            hotel="Seven Stars",
            timestamp=timestamp,
        )
        logger.info(f"Results: {results}")
        path = output_path + f"/data_{timestamp}.json"
        fs = gcsfs.GCSFileSystem(token="google_default")
        with fs.open(path, "w") as f:
            f.write(json.dumps(results, ensure_ascii=False))
        logger.info(f"Results written to '{path}'")

    def aggregate(self, input_path: str, output_path: str) -> None:
        fs = gcsfs.GCSFileSystem(token="google_default")
        paths = fs.glob(input_path + "/*.json")
        logger.info(f"Found {len(paths)} files: {paths}")
        dfs = []
        for path in paths:
            logger.info(f"Processing path '{path}'")
            # Do not use `read_text` or `read`; for some reason they
            # truncate content regardless of block size/length
            data = json.loads(fs.cat_file(path).decode("utf-8"))
            dfs.append(
                pd.DataFrame(
                    [
                        {
                            **{k: v for k, v in data.items() if k != "prices"},
                            **dict(room_name=row["room_name"], price=price),
                        }
                        for row in data["prices"]
                        for price in row["room_prices"]
                    ]
                ).assign(
                    collection_date=lambda df: pd.to_datetime(df["timestamp"], unit="s")
                )
            )
        df = pd.concat(dfs, axis="rows", ignore_index=True)
        logger.info(f"Aggregated data: {df}")
        df.info()
        path = output_path + "/data.parquet"
        df.to_parquet(path, index=False)
        logger.info(f"Data written to '{path}'")

    def analyze(self, input_path: str, webook_url: str) -> None:
        df = pd.read_parquet(input_path)
        logger.info(f"Price data: {df}")
        df.info()
        price_alerts = (
            df.pipe(
                lambda df: pd.concat(
                    [
                        df,
                        df[df["room_name"] == "1 Junior Suite Island View"].assign(
                            price=df["price"] * 0.9
                        ),
                    ],
                    ignore_index=True,
                )
            )
            .sort_values(
                ["room_name", "start_date", "stop_date", "price", "collection_date"]
            )
            .groupby(["room_name", "start_date", "stop_date"])
            .agg(
                n_dates=("collection_date", "nunique"),
                n_prices=("price", "nunique"),
                min_price=("price", "min"),
                min_price_date=("collection_date", "first"),
                max_date=("collection_date", "max"),
                all_prices=("price", "unique"),
            )
            .pipe(lambda df: df[df["n_prices"] > 1])
            # .pipe(lambda df: df[df['min_price_date'] == df['max_date']])
            .reset_index()
        )
        if len(price_alerts) > 0:
            logger.info(f"Found {len(price_alerts)} price alerts:\n{price_alerts}")
            table = (
                price_alerts[
                    ["room_name", "start_date", "stop_date", "min_price", "all_prices"]
                ]
                .assign(
                    all_prices=lambda df: df["all_prices"].apply(
                        lambda v: ", ".join(map(str, v))
                    )
                )
                .rename(
                    columns={
                        "start_date": "check_in",
                        "stop_date": "check_out",
                        "min_price": "new_low_price",
                        "all_prices": "all_past_prices",
                    }
                )
                .to_markdown(index=False, tablefmt="github")
            )
            message = (
                "Found new low prices on Seven Stars rooms!  "
                "Here the rooms and check-in/check-out periods with lower prices than those ever seen before:\n"
                f"```\n{table}\n```\n\n"
                f"For more details see {LOOKER_REPORT_URL}."
            )
            logger.info(f"Alert message:\n{message}")
            res = requests.post(webook_url, json={"text": message})
            res.raise_for_status()
        else:
            logger.info("No price alerts found")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fire.Fire(HotelPrices)
