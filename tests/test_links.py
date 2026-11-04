from shelly_qt.links import clean_env


def test_clean_env_strips_pixi():
    pre = "/home/u/proj/.pixi/envs/default"
    env = clean_env({
        "CONDA_PREFIX": pre, "PIXI_PROJECT_ROOT": "/home/u/proj",
        "PATH": f"{pre}/bin:/usr/bin", "XDG_DATA_DIRS": f"{pre}/share:/usr/share",
        "LD_LIBRARY_PATH": f"{pre}/lib", "QT_PLUGIN_PATH": f"{pre}/plugins",
        "HOME": "/home/u", "DISPLAY": ":0", "XDG_RUNTIME_DIR": "/run/user/1000",
    })
    assert env["PATH"] == "/usr/bin"
    assert env["XDG_DATA_DIRS"] == "/usr/share"
    assert "CONDA_PREFIX" not in env and "LD_LIBRARY_PATH" not in env and "QT_PLUGIN_PATH" not in env
    assert env["DISPLAY"] == ":0" and env["XDG_RUNTIME_DIR"] == "/run/user/1000"
