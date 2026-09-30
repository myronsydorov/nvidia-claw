from warden.adapters.registry import ADAPTER_CATALOGUE, ADAPTER_FACTORIES, FIXED_ADAPTERS


def test_catalogue_covers_every_fixed_and_factory_adapter() -> None:
    assert set(ADAPTER_CATALOGUE) == set(FIXED_ADAPTERS) | set(ADAPTER_FACTORIES)


def test_fixed_adapters_have_no_declared_parameters() -> None:
    for name in FIXED_ADAPTERS:
        assert ADAPTER_CATALOGUE[name].parameters == ()


def test_factory_adapters_declare_at_least_one_parameter() -> None:
    for name in ADAPTER_FACTORIES:
        assert len(ADAPTER_CATALOGUE[name].parameters) >= 1


def test_fixed_adapters_are_real_adapter_instances_matching_their_name() -> None:
    for name, adapter in FIXED_ADAPTERS.items():
        assert adapter.name == name
