from shelly_qt import conflicts as c

MSG = ('Could not install "shelly" because it would remove a package that provides "shelly=3.1.10", '
       'which "shelly-flatpak-backend" requires. Review the affected packages before continuing.\n'
       'Database path: /var/lib/pacman\n\nTechnical details: libalpm (45): could not satisfy dependencies')

BIN = {"Name": "shelly-bin", "PackageBase": "shelly-bin", "Provides": ["shelly"]}
FB_BIN = {"Name": "shelly-flatpak-backend-bin", "PackageBase": "shelly-bin",
          "Provides": ["shelly-flatpak-backend=3.2.0"]}
FB_GIT = {"Name": "shelly-flatpak-backend-git", "PackageBase": "shelly-git",
          "Provides": ["shelly-flatpak-backend"]}
FB = {"Name": "shelly-flatpak-backend", "PackageBase": "shelly"}


def test_find_blockers():
    assert c.find_blockers([MSG, MSG, "other"]) == [
        c.Blocker("shelly", "shelly=3.1.10", "shelly-flatpak-backend")]


def test_install_request():
    r = c.install_request(["install", "aur", "shelly-bin", "--needed"])
    assert (r.backend, r.targets, r.flags) == ("aur", ["shelly-bin"], ["--needed"])
    assert r.args(["x"]) == ["install", "aur", "shelly-bin", "x", "--needed"]
    assert c.install_request(["remove", "standard", "x"]) is None


def test_pick_same_package_base():
    b = c.find_blockers([MSG])[0]
    req = c.install_request(["install", "aur", "shelly-bin"])
    assert c.pick_replacement(b, req, [BIN], [FB, FB_GIT, FB_BIN])["Name"] == "shelly-flatpak-backend-bin"


def test_pick_by_flavour_when_base_unknown():
    b = c.find_blockers([MSG])[0]
    req = c.install_request(["install", "aur", "shelly-git"])
    assert c.pick_replacement(b, req, [], [FB_BIN, FB_GIT])["Name"] == "shelly-flatpak-backend-git"


def test_no_guess_from_unrelated_source():
    b = c.find_blockers([MSG])[0]
    req = c.install_request(["install", "aur", "shelly"])
    unrelated = {"Name": "other-backend", "PackageBase": "other", "Provides": ["shelly-flatpak-backend"]}
    assert c.pick_replacement(b, req, [], [unrelated]) is None


def test_removal_args():
    assert c.removal_args(c.find_blockers([MSG])) == [
        "remove", "standard", "shelly-flatpak-backend", "--no-cascade"]
