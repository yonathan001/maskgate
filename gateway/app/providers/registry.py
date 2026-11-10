from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml

from app.config import get_settings
from app.providers.base import Provider
from app.providers.mock import MockProvider


@dataclass
class ProviderRoute:
    provider: str
    upstream_model: str


@dataclass
class PricePer1K:
    input: Decimal = Decimal("0.0")
    output: Decimal = Decimal("0.0")


@dataclass
class ModelConfig:
    name: str
    providers: list[ProviderRoute]
    price_per_1k: PricePer1K = field(default_factory=PricePer1K)


class ModelRegistry:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or get_settings().resolve_models_path()
        self.models: dict[str, ModelConfig] = {}
        self.providers: dict[str, Provider] = {
            "mock": MockProvider(),
        }
        self.load_config()

    def register_provider(self, name: str, provider: Provider) -> None:
        self.providers[name] = provider

    def get_provider(self, name: str) -> Provider | None:
        return self.providers.get(name)

    def load_config(self) -> None:
        if not self.config_path.exists():
            # Fallback default configuration if file missing
            self.models["mock-fast"] = ModelConfig(
                name="mock-fast",
                providers=[ProviderRoute(provider="mock", upstream_model="mock-fast")],
                price_per_1k=PricePer1K(input=Decimal("0.0"), output=Decimal("0.0")),
            )
            return

        with open(self.config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        models_list = data.get("models", [])
        self.models.clear()

        for item in models_list:
            name = item["name"]
            routes = [
                ProviderRoute(
                    provider=p["provider"],
                    upstream_model=p.get("upstream_model", name),
                )
                for p in item.get("providers", [])
            ]
            prices = item.get("price_per_1k", {})
            price_config = PricePer1K(
                input=Decimal(str(prices.get("input", 0.0))),
                output=Decimal(str(prices.get("output", 0.0))),
            )
            self.models[name] = ModelConfig(
                name=name,
                providers=routes,
                price_per_1k=price_config,
            )

    def get_model(self, name: str) -> ModelConfig | None:
        return self.models.get(name)

    def list_models(self) -> list[str]:
        return list(self.models.keys())


_registry: ModelRegistry | None = None


def get_model_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
