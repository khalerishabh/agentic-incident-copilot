import pytest

from demo.common.chaos import ChaosState


def test_params_keep_the_type_of_their_default():
    chaos = ChaosState()
    params = chaos.enable("memory_leak", {"kb_per_request": 512.0})
    assert params["kb_per_request"] == 512
    assert isinstance(params["kb_per_request"], int)


async def test_memory_leak_grows_instead_of_failing_requests():
    chaos = ChaosState()
    chaos.enable("memory_leak", {"kb_per_request": 4.0})
    await chaos.before_request()
    await chaos.before_request()
    assert len(chaos._leak) == 2
    assert len(chaos._leak[0]) == 4 * 1024


@pytest.mark.parametrize("params", [{"kb": 1}, {"kb_per_request": "lots"}])
def test_bad_params_are_rejected(params):
    with pytest.raises(ValueError):
        ChaosState().enable("memory_leak", params)
