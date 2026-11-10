from app.providers.registry import get_model_registry


def test_model_registry_loaded() -> None:
    registry = get_model_registry()
    models = registry.list_models()
    assert "mock-fast" in models
    model_cfg = registry.get_model("mock-fast")
    assert model_cfg is not None
    assert len(model_cfg.providers) > 0
    assert model_cfg.providers[0].provider == "mock"
