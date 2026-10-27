"""Forum theme pack engine for SigmaOS-forum-themes.

Principles: packs are declarative directories (theme.ini + css), pure
planning/validation (apply-plan never touches a forum install), preview is
a pure string composition, export is the only side effect and only writes
where the user points it. Fail-fast on invalid variants/backends.
"""
import argparse, os, re, sys, tarfile

ENGINE = {
    "name": "sigma-forum-themes",
    "summary": "Manage forum theme packs: list, plan, preview, export",
    "language": "python",
    "verbs": ["themes", "apply-plan", "preview", "export"],
    "principles": ["Abstraction", "Plan Before Act", "Fail-Fast",
                   "Defensive Programming", "KISS", "Deterministic Testing"],
}

cli_doc = """\
$ sigma-forum-themes themes ./pack
sigma-dark   Sigma Dark    dark    discourse
sigma-light  Sigma Light   light   flarum
$ sigma-forum-themes apply-plan ./pack sigma-dark --root /var/discourse --backend discourse
copy stylesheets/sigma-dark.css -> /var/discourse/stylesheets/sigma-dark.css
$ sigma-forum-themes preview ./pack sigma-dark --out /tmp/preview.html
$ sigma-forum-themes export ./pack sigma-dark --out sigma-dark.tar.gz
"""

_VARIANTS = ("light", "dark")
_BACKENDS = ("discourse", "flarum", "phpbb")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class ForumThemeError(ValueError):
    pass


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def parse_theme_ini(text):
    """Parse the [theme] INI block into a validated dict."""
    theme, section = {}, None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section != "theme" or "=" not in line:
            raise ForumThemeError(f"line {lineno}: cannot parse {line!r}")
        key, _, value = line.partition("=")
        theme[key.strip()] = value.strip()
    for required in ("name", "slug", "variant", "backend", "css"):
        if not theme.get(required):
            raise ForumThemeError(f"theme.ini missing {required!r}")
    if not _SLUG_RE.match(theme["slug"]):
        raise ForumThemeError(f"bad slug {theme['slug']!r}")
    if theme["variant"] not in _VARIANTS:
        raise ForumThemeError(
            f"variant must be one of {_VARIANTS}, got {theme['variant']!r}")
    if theme["backend"] not in _BACKENDS:
        raise ForumThemeError(
            f"backend must be one of {_BACKENDS}, got {theme['backend']!r}")
    return theme


def list_themes(pack):
    """All valid themes in pack/themes/* sorted by slug."""
    root = os.path.join(pack, "themes")
    if not os.path.isdir(root):
        raise ForumThemeError(f"no themes/ directory in pack {pack!r}")
    out = []
    for entry in sorted(os.listdir(root)):
        ini = os.path.join(root, entry, "theme.ini")
        if not os.path.isfile(ini):
            continue
        theme = parse_theme_ini(_read(ini))
        if theme["slug"] != entry:
            raise ForumThemeError(
                f"{entry}: slug {theme['slug']!r} does not match directory")
        theme["dir"] = os.path.join(root, entry)
        out.append(theme)
    if not out:
        raise ForumThemeError(f"pack {pack!r} contains no themes")
    return out


def _load(pack, slug):
    for theme in list_themes(pack):
        if theme["slug"] == slug:
            return theme
    known = ", ".join(t["slug"] for t in list_themes(pack))
    raise ForumThemeError(f"unknown theme {slug!r} (known: {known})")


_FILE_MAPS = {
    "discourse": {"css": "stylesheets/{slug}.css",
                  "yaml": "theme.yml"},
    "flarum": {"css": "less/common.less",
               "manifest": "extension.json"},
    "phpbb": {"css": "theme/{slug}/css/{slug}.css"},
}


def apply_plan(pack, slug, target_root, backend=None):
    """Pure install plan mapping pack files onto a backend layout."""
    theme = _load(pack, slug)
    if backend is not None and theme["backend"] != backend:
        raise ForumThemeError(
            f"theme {slug!r} targets {theme['backend']!r}, "
            f"not {backend!r}")
    file_map = _FILE_MAPS[theme["backend"]]
    source_names = {"css": theme["css"], "yaml": "theme.yml",
                    "manifest": "extension.json"}
    plan = []
    for source, dest_tmpl in sorted(file_map.items()):
        src = os.path.join(theme["dir"], source_names.get(source, source))
        if source == "css" and not os.path.isfile(src):
            raise ForumThemeError(
                f"theme {slug!r} is missing its css file "
                f"{theme['css']!r}")
        if not os.path.isfile(src):
            continue  # optional piece absent: skip, don't fail
        plan.append({"kind": "copy", "src": src,
                     "dst": os.path.join(target_root,
                                         dest_tmpl.format(slug=slug))})
    activate = {"discourse": "rake themes:refresh cache",
                "flarum": "php flarum cache:clear",
                "phpbb": "php bin/phpbbcli.php cache:purge"}[theme["backend"]]
    plan.append({"kind": "cmd", "cmd": activate})
    return {"theme": theme, "steps": plan}


_PREVIEW_TEMPLATE = """<!doctype html>
<html lang="en" data-backend="{backend}" data-variant="{variant}">
<head>
<meta charset="utf-8">
<title>{name} &mdash; forum theme preview</title>
<style>
/* {slug}.css */
{css}
</style>
</head>
<body class="theme-{slug}">
<h1>{name}</h1>
<p>Variant: {variant} &middot; Backend: {backend}</p>
<p><a href="#">A link</a> &middot; <button>A button</button></p>
</body>
</html>
"""


def preview(pack, slug):
    """Pure HTML preview composing the theme's CSS into a template."""
    theme = _load(pack, slug)
    css_path = os.path.join(theme["dir"], theme["css"])
    if not os.path.isfile(css_path):
        raise ForumThemeError(
            f"theme {slug!r} is missing its css file {theme['css']!r}")
    css = _read(css_path)
    # a `{word}` token would collide with str.format placeholders
    if re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", css):
        raise ForumThemeError(
            f"css of {slug!r} contains template braces; refusing to render")
    return _PREVIEW_TEMPLATE.format(
        name=theme["name"], slug=theme["slug"], variant=theme["variant"],
        backend=theme["backend"], css=css)


def export(pack, slug, out_path):
    """Bundle a theme directory into a gzipped tar. Returns member count."""
    theme = _load(pack, slug)
    members = []
    for dirpath, dirnames, filenames in os.walk(theme["dir"]):
        dirnames.sort()
        for fname in sorted(filenames):
            full = os.path.join(dirpath, fname)
            members.append((full, os.path.join(slug,
                                               os.path.relpath(full,
                                                               theme["dir"]))))
    if not members:
        raise ForumThemeError(f"theme {slug!r} has no files to export")
    with tarfile.open(out_path, "w:gz") as tar:
        for full, arcname in sorted(members, key=lambda m: m[1]):
            tar.add(full, arcname=arcname)
    return len(members)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=ENGINE["name"],
                                description=ENGINE["summary"])
    sub = p.add_subparsers(dest="cmd", required=True)
    th = sub.add_parser("themes", help="list themes in a pack")
    th.add_argument("pack")
    ap = sub.add_parser("apply-plan", help="plan a theme install (dry run)")
    ap.add_argument("pack")
    ap.add_argument("slug")
    ap.add_argument("--root", required=True)
    ap.add_argument("--backend", choices=list(_BACKENDS), default=None)
    pv = sub.add_parser("preview", help="render an HTML preview")
    pv.add_argument("pack")
    pv.add_argument("slug")
    pv.add_argument("--out", default=None)
    ex = sub.add_parser("export", help="export a theme as tar.gz")
    ex.add_argument("pack")
    ex.add_argument("slug")
    ex.add_argument("--out", required=True)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "themes":
            for t in list_themes(args.pack):
                print(f"{t['slug']:<16} {t['name']:<20} "
                      f"{t['variant']:<6} {t['backend']}")
        elif args.cmd == "apply-plan":
            plan = apply_plan(args.pack, args.slug, args.root,
                              backend=args.backend)
            for step in plan["steps"]:
                if step["kind"] == "copy":
                    print(f"copy {step['src']} -> {step['dst']}")
                else:
                    print(f"run  {step['cmd']}")
        elif args.cmd == "preview":
            html = preview(args.pack, args.slug)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as fh:
                    fh.write(html)
                print(f"wrote {len(html)} bytes -> {args.out}")
            else:
                print(html)
        elif args.cmd == "export":
            n = export(args.pack, args.slug, args.out)
            print(f"exported {n} file(s) -> {args.out}")
        return 0
    except (ForumThemeError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _build_pack(d):
    """Test fixture: a pack with a dark discourse theme + light flarum."""
    pack = os.path.join(d, "pack")
    dark = os.path.join(pack, "themes", "sigma-dark")
    light = os.path.join(pack, "themes", "sigma-light")
    os.makedirs(dark)
    os.makedirs(light)
    with open(os.path.join(dark, "theme.ini"), "w") as fh:
        fh.write("[theme]\nname = Sigma Dark\nslug = sigma-dark\n"
                 "variant = dark\nbackend = discourse\ncss = theme.css\n")
    with open(os.path.join(dark, "theme.css"), "w") as fh:
        fh.write("body { background: #1e1e2e; color: #cdd6f4; }\n")
    with open(os.path.join(dark, "theme.yml"), "w") as fh:
        fh.write("name: sigma-dark\ncomponent: colored\n")
    with open(os.path.join(light, "theme.ini"), "w") as fh:
        fh.write("[theme]\nname = Sigma Light\nslug = sigma-light\n"
                 "variant = light\nbackend = flarum\ncss = theme.css\n")
    with open(os.path.join(light, "theme.css"), "w") as fh:
        fh.write("body { background: #eff1f5; color: #4c4f69; }\n")
    return pack


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        pack = _build_pack(d)

        # listing + ini validation
        themes = list_themes(pack)
        assert [t["slug"] for t in themes] == ["sigma-dark", "sigma-light"]
        assert themes[0]["variant"] == "dark" and \
            themes[1]["backend"] == "flarum"
        for bad_ini in (
            "[theme]\nname = X\n",                                   # missing keys
            "[theme]\nname=X\nslug=Bad Slug\nvariant=dark\n"
            "backend=discourse\ncss=theme.css\n",                    # bad slug
            "[theme]\nname=X\nslug=x\nvariant=neon\nbackend=discourse\n"
            "css=theme.css\n",                                       # bad variant
            "[theme]\nname=X\nslug=x\nvariant=dark\nbackend=drupal\n"
            "css=theme.css\n",                                       # bad backend
            "name = X\n",                                            # no section
        ):
            try:
                parse_theme_ini(bad_ini)
            except ForumThemeError:
                pass
            else:
                raise AssertionError(f"ini accepted: {bad_ini!r}")

        # apply-plan
        plan = apply_plan(pack, "sigma-dark", "/var/discourse",
                          backend="discourse")
        copies = [s for s in plan["steps"] if s["kind"] == "copy"]
        assert [c["dst"] for c in copies] == [
            "/var/discourse/stylesheets/sigma-dark.css",
            "/var/discourse/theme.yml",
        ]
        assert plan["steps"][-1] == {"kind": "cmd",
                                     "cmd": "rake themes:refresh cache"}
        flarum = apply_plan(pack, "sigma-light", "/srv/flarum")
        assert any(s.get("dst", "").endswith("less/common.less")
                   for s in flarum["steps"])
        assert not any(s.get("dst", "").endswith("extension.json")
                       for s in flarum["steps"])   # absent optional file
        for bad in (lambda: apply_plan(pack, "sigma-dark", "/x",
                                       backend="flarum"),
                    lambda: apply_plan(pack, "ghost", "/x")):
            try:
                bad()
            except ForumThemeError:
                pass
            else:
                raise AssertionError("expected ForumThemeError")

        # preview
        html = preview(pack, "sigma-dark")
        assert "#1e1e2e" in html and "sigma-dark" in html
        assert 'data-variant="dark"' in html
        assert 'data-backend="discourse"' in html
        # css with template braces is refused (would corrupt rendering)
        with open(os.path.join(pack, "themes", "sigma-light", "theme.css"),
                  "w") as fh:
            fh.write("body { color: {oops}; }\n")
        try:
            preview(pack, "sigma-light")
        except ForumThemeError as e:
            assert "template braces" in str(e)
        else:
            raise AssertionError("brace css accepted")
        with open(os.path.join(pack, "themes", "sigma-light", "theme.css"),
                  "w") as fh:
            fh.write("body { background: #eff1f5; }\n")

        # export
        out = os.path.join(d, "sigma-dark.tar.gz")
        n = export(pack, "sigma-dark", out)
        assert n == 3  # theme.ini + theme.css + theme.yml
        import tarfile as tf
        with tf.open(out, "r:gz") as tar:
            names = sorted(tar.getnames())
        assert names == ["sigma-dark/theme.css", "sigma-dark/theme.ini",
                         "sigma-dark/theme.yml"]

        # slug/dir mismatch is caught
        os.rename(os.path.join(pack, "themes", "sigma-light"),
                  os.path.join(pack, "themes", "renamed"))
        try:
            list_themes(pack)
        except ForumThemeError as e:
            assert "does not match" in str(e)
        else:
            raise AssertionError("slug/dir mismatch accepted")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
