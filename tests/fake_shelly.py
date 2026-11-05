#!/usr/bin/env python3
"""Stand-in for the `shelly` CLI speaking the --ui-mode protocol (for tests and demos).

Use with: SHELLY_BIN="python3 tests/fake_shelly.py" SHELLY_ELEVATE="" python -m shelly_qt
"""
import base64
import json
import sys
import time


def frame(obj):
    sys.stdout.write("[JSON]" + base64.b64encode(json.dumps(obj).encode()).decode() + "[/JSON]\n")
    sys.stdout.flush()


def read_answer():
    line = sys.stdin.readline()
    s, e = line.find("[JSON]"), line.find("[/JSON]")
    return json.loads(base64.b64decode(line[s + 6:e])) if s >= 0 else {}


PKGS = [
    {"Name": "firefox", "Version": "133.0-1", "Repository": "extra", "Size": 250_000_000,
     "Description": "Fast, Private & Safe Web Browser", "Installed": True, "Explicit": True,
     "InstalledSize": 250_000_000, "Url": "https://www.mozilla.org/firefox/", "Depends": ["gtk3", "nss"]},
    {"Name": "git", "Version": "2.47.1-1", "Repository": "extra", "Size": 30_000_000,
     "Description": "the fast distributed version control system", "Installed": True, "Explicit": True,
     "InstalledSize": 30_000_000},
    {"Name": "zed", "Version": "0.165.4-1", "Repository": "extra", "Size": 90_000_000,
     "Description": "A high-performance, multiplayer code editor", "Installed": False},
    {"Name": "neovim", "Version": "0.10.2-2", "Repository": "extra", "Size": 28_000_000,
     "Description": "Fork of Vim aiming to improve user experience", "Installed": False},
    {"Name": "glibc", "Version": "2.40+r16-1", "Repository": "core", "Size": 48_000_000,
     "Description": "GNU C Library", "Installed": True, "Explicit": False, "InstalledSize": 48_000_000},
]
AUR = [
    {"Id": 1, "Name": "yay", "PackageBaseId": 1, "PackageBase": "yay", "Version": "12.4.2-1",
     "Description": "Yet another yogurt. Pacman wrapper and AUR helper written in go.",
     "NumVotes": 2500, "Popularity": 31.2, "Maintainer": "jguer", "FirstSubmitted": 1475000000,
     "LastModified": 1730000000, "Url": "https://github.com/Jguer/yay"},
    {"Id": 2, "Name": "paru", "PackageBaseId": 2, "PackageBase": "paru", "Version": "2.0.4-1",
     "Description": "Feature packed AUR helper", "NumVotes": 1100, "Popularity": 18.4,
     "Maintainer": "Morganamilo", "FirstSubmitted": 1600000000, "LastModified": 1729000000},
    {"Id": 3, "Name": "zed-git", "PackageBaseId": 3, "PackageBase": "zed-git", "Version": "0.166.0.r1-1",
     "Description": "High-performance, multiplayer code editor (git build)", "NumVotes": 40,
     "Popularity": 1.2, "Maintainer": "someone", "FirstSubmitted": 1700000000, "LastModified": 1730000000},
    # a split package base: shelly-bin builds shelly-flatpak-backend-bin too
    {"Id": 4, "Name": "shelly-bin", "PackageBaseId": 4, "PackageBase": "shelly-bin", "Version": "3.2.0-1",
     "Description": "Arch package manager front end (binary)", "Provides": ["shelly"],
     "Conflicts": ["shelly", "shelly-git"], "NumVotes": 10, "Popularity": 0.5},
    {"Id": 5, "Name": "shelly-flatpak-backend-bin", "PackageBaseId": 4, "PackageBase": "shelly-bin",
     "Version": "3.2.0-1", "Description": "Flatpak backend for Shelly (binary)",
     "Provides": ["shelly-flatpak-backend=3.2.0"], "Conflicts": ["shelly-flatpak-backend"],
     "Depends": ["shelly-bin=3.2.0-1", "flatpak"], "NumVotes": 3, "Popularity": 0.2},
    {"Id": 6, "Name": "shelly-flatpak-backend-git", "PackageBaseId": 6, "PackageBase": "shelly-git",
     "Version": "3.2.0.r5-1", "Description": "Flatpak backend for Shelly (git)",
     "Provides": ["shelly-flatpak-backend"], "NumVotes": 1, "Popularity": 0.1},
]
GIMP = {"name": "GIMP", "app_id": "org.gimp.GIMP", "summary": "Image editor", "developer_name": "GIMP team"}
FLATHUB = [
    {"name": "Krita", "app_id": "org.kde.krita", "summary": "Digital painting",
     "developer_name": "KDE", "verification_verified": True, "project_license": "GPL-3.0"},
    {"name": "Zed", "app_id": "dev.zed.Zed", "summary": "High-performance, multiplayer code editor",
     "developer_name": "Zed Industries", "verification_verified": True, "project_license": "GPL-3.0"},
]

args = [a for a in sys.argv[1:] if a != "--ui-mode"]
cmd = " ".join(args)

if args == ["-Ssv"]:
    frame(PKGS)
elif args[:2] == ["search", "standard"]:
    q = args[2].lower() if len(args) > 2 and not args[2].startswith("-") else ""
    # like the real CLI, sync-db search results say nothing about what is installed
    hits = [{k: v for k, v in p.items() if k not in ("Installed", "Explicit")}
            for p in PKGS if q in p["Name"] or q in p["Description"].lower()]
    frame(hits[:2])  # standard search streams pages
    if hits[2:]:
        frame(hits[2:])
elif args == ["-Ls"]:
    # the local db holds foreign (AUR) packages too: yay, and shelly-bin providing "shelly"
    frame([p for p in PKGS if p["Installed"]] + [
        {"Name": "yay", "Version": "12.4.1-1", "Repository": "local", "Description": AUR[0]["Description"],
         "Installed": True, "Explicit": True, "InstalledSize": 9_000_000},
        {"Name": "shelly-bin", "Version": "3.2.0-1", "Repository": "local", "Provides": ["shelly"],
         "Description": AUR[3]["Description"], "Installed": True, "Explicit": True,
         "InstalledSize": 20_000_000}])
elif args[:1] == ["-Ssdi"]:
    frame(next((dict(p, RequiredBy=["base"]) for p in PKGS if p["Name"] == args[1]), {}))
elif args == ["-P"]:
    frame({"Packages": [{"Name": "firefox", "CurrentVersion": "133.0-1", "NewVersion": "134.0-1",
                         "Repository": "extra", "DownloadSize": 70_000_000, "SizeDifference": 1_200_000}],
           "Aur": [{"Name": "yay", "Version": "12.4.1-1", "NewVersion": "12.4.2-1"}],
           "Flatpak": [{"Name": "GIMP", "Id": "org.gimp.GIMP", "Version": "2.10.38", "NewVersion": "3.0.0",
                        "Branch": "stable", "Remote": "flathub"},
                       {"Name": "Krita", "Id": "org.kde.krita", "Version": "5.2.6", "NewVersion": "5.2.9",
                        "Branch": "stable", "Remote": "flathub"}]})
elif args[:2] == ["list", "aur"]:
    frame(AUR[:1])
elif args[:2] == ["search", "aur"]:
    if "--pkgbuild" in args:
        frame([{"Name": args[2], "PkgBuild": "pkgname=%s\npkgver=1.0\npkgrel=1\n" % args[2]}])
    elif args[2:] == ["fail"]:
        frame({"$kind": "alpm.error", "ErrorMessage": "AUR RPC unreachable", "Level": "Error"})
        sys.exit(1)
    else:
        words = [w.lower() for w in args[2:]]
        # short queries return the classic fixed list (yay + paru); longer ones filter
        frame(AUR[:2] if len(" ".join(words)) < 3 else
              [p for p in AUR if all(w in (p["Name"] + p["Description"]).lower() for w in words)])
elif args == ["-Lf"]:
    frame([{"Id": "org.gimp.GIMP", "Name": "GIMP", "Version": "2.10.38", "Remote": "flathub",
            "Kind": 0, "InstalledSize": 400_000_000, "InstallLevel": 0}])
elif args[:2] == ["search", "flatpak"]:
    q = args[2].lower()
    # one- or two-letter queries return the classic fixed list (Krita + installed GIMP)
    hits = FLATHUB[:1] + [GIMP] if len(q) < 3 else \
        [h for h in FLATHUB + [GIMP] if q in (h["name"] + h["app_id"] + h["summary"]).lower()]
    frame({"hits": hits, "totalHits": len(hits)})
elif args[:2] == ["list", "appimage"]:
    frame([{"Name": "obsidian", "DesktopName": "Obsidian", "Version": "1.7.7", "SizeOnDisk": 120_000_000,
            "Path": "/home/user/Applications/Obsidian.AppImage"}])
elif args[:2] == ["list-updates", "appimage"]:
    frame([{"Name": "obsidian", "Version": "1.8.0", "IsUpdateAvailable": True}])
elif args[:2] == ["config", "list"]:
    frame({"FileSizeDisplay": "Megabytes", "ProgressBarStyle": "Shell", "CollapsePkgbuildDiff": True,
           "DisableFlatpakUpdateCheck": False, "NativePackageBackend": "libalpm"})
elif args[:2] == ["config", "set"]:
    frame({"$kind": "alpm.info", "EventType": "InformationalOutput", "Message": "saved"})
elif args[:1] in (["install"], ["remove"], ["upgrade"], ["update"], ["sync"], ["purify"], ["utility"]):
    frame({"$kind": "alpm.info", "EventType": "TransactionStart", "Message": f"Starting: {cmd}"})
    if args[:2] == ["install", "aur"]:
        frame({"$kind": "q.pkgbuilddiff", "QuestionId": "p1", "PackageName": args[2],
               "OldPkgbuild": "", "NewPkgbuild": "pkgname=%s\n" % args[2],
               "DiffLines": ["+pkgname=%s" % args[2]], "Warnings": []})
        if not read_answer().get("ProceedWithUpdate"):
            frame({"$kind": "alpm.error", "ErrorMessage": "Build declined.", "Level": "Error"})
            sys.exit(1)
        if "shelly-bin" in args and "shelly-flatpak-backend-bin" not in args:
            # what libalpm says when the replaced package is pinned by a dependent
            frame({"$kind": "alpm.error", "Level": "Error", "ErrorMessage":
                   'Could not install "shelly" because it would remove a package that provides '
                   '"shelly=3.1.10", which "shelly-flatpak-backend" requires. Review the affected '
                   'packages before continuing.\nDatabase path: /var/lib/pacman\n\n'
                   'Technical details: libalpm (45): could not satisfy dependencies'})
            frame({"$kind": "alpm.error", "Level": "Error", "ErrorMessage":
                   "Could not complete the package operation.\nPackage: shelly-bin"})
            sys.exit(1)
    if args[:1] in (["install"], ["remove"], ["upgrade"]):
        frame({"$kind": "q.transaction", "QuestionId": "t1", "Action": args[0],
               "QuestionText": f"Proceed with {args[0]}?",
               "Packages": [{"Name": n, "Version": "1.0-1", "Repository": "extra", "Source": "repo",
                             "Role": "target", "DownloadSize": 1_000_000, "InstalledSize": 3_000_000}
                            for n in args[2:] if not n.startswith("-")] or
                           [{"Name": "firefox", "Version": "134.0-1", "Role": "upgrade", "Source": "repo"}],
               "TotalDownloadSize": 1_000_000, "TotalInstalledSize": 3_000_000, "NetInstalledSize": 3_000_000})
        ans = read_answer()
        if not ans.get("Accept"):
            frame({"$kind": "alpm.info", "EventType": "TransactionCancelled", "Message": "Cancelled."})
            sys.exit(0)
    for pct in range(0, 101, 25):
        frame({"$kind": "alpm.progress", "PackageName": "pkg", "ProgressType": "Download",
               "Percent": pct})
        time.sleep(0.05)
    frame({"$kind": "alpm.info", "EventType": "TransactionDone", "Message": "Done."})
else:
    frame({"$kind": "alpm.error", "ErrorMessage": f"unknown command {cmd}", "Level": "Error"})
    sys.exit(1)
