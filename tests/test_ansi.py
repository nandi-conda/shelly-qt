from shelly_qt import ansi


def test_strip_and_colours():
    assert ansi.strip("\x1b[1;32m==>\x1b[0m done") == "==> done"
    runs, end = ansi.parse("\x1b[31mred\x1b[0m plain")
    assert runs[0] == ("red", ansi.Attrs(fg=ansi.PALETTE16[1]))
    assert runs[1] == (" plain", ansi.Attrs())
    assert end == ansi.Attrs()


def test_attributes_carry_across_lines_and_extended_colours():
    _, end = ansi.parse("\x1b[1;38;5;196mstart")
    assert end.bold and end.fg == (255, 0, 0)
    runs, _ = ansi.parse("more", end)
    assert runs == [("more", end)]
    runs, _ = ansi.parse("\x1b[38;2;1;2;3mx")
    assert runs[0][1].fg == (1, 2, 3)


def test_drops_cursor_osc_and_handles_overwrite():
    assert ansi.strip("\x1b]8;;https://x\x1b\\link\x1b]8;;\x1b\\ \x1b[2K\x1b[1Gok") == "link ok"
    assert ansi.strip("50%\r100%") == "100%"
    assert ansi.strip("abc\bd") == "abd"
