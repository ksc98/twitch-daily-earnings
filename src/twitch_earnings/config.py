from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    twitch_client_id: str
    twitch_client_secret: str
    twitch_bot_name: str

    sub_split_percent: float = 50.0
    ad_cpm: float = 3.50

    @property
    def sub_split(self) -> float:
        return self.sub_split_percent / 100.0

    @property
    def tier_revenue(self) -> dict[str, float]:
        """Streamer's cut per sub tier based on split percentage."""
        base_prices = {"1000": 4.99, "2000": 9.99, "3000": 24.99}
        return {k: v * self.sub_split for k, v in base_prices.items()}
