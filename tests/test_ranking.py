from shelly_qt.ranking import penalty, rank_rows, tier, EXACT, BOUNDARY_PREFIX, WORD, DESCRIPTION


def names(rows):
    return [(r.get("Name"), r.get("_source")) for r in rows]


def test_tiers():
    assert tier({"Name": "zed"}, "zed") == EXACT
    assert tier({"AppId": "dev.zed.Zed", "Name": "Zed"}, "zed") == EXACT
    assert tier({"Name": "zed-bin"}, "zed") == BOUNDARY_PREFIX
    assert tier({"Name": "python-zed"}, "zed") == WORD
    assert tier({"Name": "editor", "Description": "the zed editor"}, "zed") == DESCRIPTION


def test_variant_penalties():
    assert penalty({"Name": "firefox-debug"}, "firefox") == 1
    assert penalty({"Name": "firefox-git"}, "firefox git") == 0
    assert penalty({"Name": "libfoo"}, "foo") == 1
    assert penalty({"Name": "python-requests"}, "requests") == 1


def test_mixed_sources_rank_exact_official_first():
    rows = [
        {"Name": "firefox-nightly", "_source": "aur", "NumVotes": 300},
        {"Name": "firefox-esr-bin", "_source": "aur", "NumVotes": 50},
        {"Name": "librewolf", "_source": "aur", "NumVotes": 900, "Description": "firefox fork"},
        {"Name": "firefox", "_source": "aur", "NumVotes": 5},
        {"Name": "Firefox", "AppId": "org.mozilla.firefox", "_source": "flatpak",
         "installs_last_month": 200000, "verification_verified": True},
        {"Name": "firefox", "_source": "repo", "Repository": "extra"},
        {"Name": "firefox-i18n-de", "_source": "repo", "Repository": "extra"},
    ]
    out = rank_rows(rows, "firefox")
    assert names(out)[:2] == [("Firefox", "flatpak"), ("firefox", "repo")] or \
        names(out)[:2] == [("firefox", "repo"), ("Firefox", "flatpak")]
    order = [n for n, _ in names(out)]
    assert order.index("firefox-esr-bin") < order.index("firefox-nightly")  # -nightly is a variant
    assert order.index("firefox-i18n-de") > order.index("firefox-esr-bin")
    assert order[-1] == "librewolf"  # description-only match
    assert [r["_rank"] for r in out] == list(range(1, len(rows) + 1))
    assert out[0]["_match"] == "exact" and out[-1]["_match"] == "description"


def test_popular_aur_beats_obscure_at_same_tier():
    out = rank_rows([{"Name": "yay-bin", "NumVotes": 10}, {"Name": "yay-git", "NumVotes": 5000},
                     {"Name": "yay-tools", "NumVotes": 900}], "yay", "aur")
    assert [r["Name"] for r in out] == ["yay-tools", "yay-bin", "yay-git"]
