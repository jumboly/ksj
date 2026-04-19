from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from ksj import __version__, html_cache
from ksj.catalog import Catalog, Dataset, load_catalog
from ksj.catalog.loader import CatalogNotFoundError
from ksj.catalog.refresh import (
    RefreshSummary,
    diff_catalogs,
    refresh_catalog,
    save_catalog,
)
from ksj.downloader import (
    DownloadResult,
    DownloadTarget,
    ManifestEntry,
    download_many,
    filename_from_url,
    load_manifest,
    pick_targets,
    save_manifest,
)
from ksj.downloader.manifest import LOCAL_URL_PREFIX
from ksj.html_cache import CachePolicy
from ksj.integrator import (
    DEFAULT_TARGET_CRS,
    DownloadRequiredError,
    NoSourcesError,
)
from ksj.integrator import (
    integrate as integrate_dataset,
)
from ksj.reader import NoMatchingFormatError

app = typer.Typer(
    name="ksj",
    help="国土数値情報 (KSJ) のカタログ管理・ダウンロード・統合 CLI",
    no_args_is_help=True,
    add_completion=False,
)

catalog_app = typer.Typer(
    name="catalog",
    help="カタログ操作 (refresh / diff)",
    no_args_is_help=True,
)
app.add_typer(catalog_app, name="catalog")

html_app = typer.Typer(
    name="html",
    help="KSJ サイトの HTML をローカルキャッシュする (fetch / list)",
    no_args_is_help=True,
)
app.add_typer(html_app, name="html")

console = Console()
err_console = Console(stderr=True)


def _configure_logging() -> None:
    """``ksj`` ロガーに rich ハンドラを付ける。

    root を掴まないのは、ライブラリとして import する利用側の logging 設定を
    上書きしないため。冪等にして繰り返し import で handler が累積するのを防ぐ。
    propagate はデフォルトの True のまま残す (caplog など root attach テスト互換)。
    """
    logger = logging.getLogger("ksj")
    if any(isinstance(h, RichHandler) for h in logger.handlers):
        return
    handler = RichHandler(console=err_console, show_time=False, show_path=False, markup=False)
    handler.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)


@app.callback()
def _main() -> None:
    """Typer がサブコマンド構造になるよう明示的なコールバックを置く。"""
    _configure_logging()


@app.command()
def version() -> None:
    """バージョンを表示する。"""
    typer.echo(__version__)


def _load_or_exit() -> Catalog:
    """カタログを読み込み、見つからなければ説明付きで終了する。"""
    try:
        return load_catalog()
    except CatalogNotFoundError as exc:
        err_console.print(f"[red]catalog/datasets.yaml が見つかりません: {exc}[/red]")
        raise typer.Exit(code=1) from exc


def _collect_scopes(dataset: Dataset) -> list[str]:
    """データセットに現れる scope を重複除去して挿入順で返す。"""
    return list(
        dict.fromkeys(file.scope for version in dataset.versions.values() for file in version.files)
    )


def _category_matches(dataset: Dataset, query: str | None) -> bool:
    if query is None:
        return True
    return dataset.category is not None and query in dataset.category


def _run_refresh(
    *,
    only: list[str] | None,
    parallel: int,
    rate: float,
    cache_dir: Path,
    cache_policy: CachePolicy,
    status_message: str,
) -> tuple[Catalog, RefreshSummary]:
    with console.status(f"[cyan]{status_message}[/cyan]", spinner="dots"):
        return asyncio.run(
            refresh_catalog(
                only=only,
                parallel=parallel,
                rate_per_sec=rate,
                cache_dir=cache_dir,
                cache_policy=cache_policy,
            )
        )


def _print_summary_warnings(summary: RefreshSummary) -> None:
    if summary.unsupported:
        console.print(
            f"[yellow]フォームベース配布 (自動 URL 取得不可)[/yellow]: "
            f"{', '.join(summary.unsupported)}"
        )
    if summary.warnings:
        console.print(f"[yellow]{len(summary.warnings)} 件の警告[/yellow] (先頭 3 件のみ):")
        for w in summary.warnings[:3]:
            console.print(f"  {w}")


@app.command("list")
def list_datasets(
    category: Annotated[
        str | None,
        typer.Option(
            "--category",
            help="カテゴリの部分一致でフィルタ (例: '災害' '土地利用')。",
        ),
    ] = None,
    scope: Annotated[
        str | None,
        typer.Option(
            "--scope",
            help="任意の scope を含むデータセットのみ表示 (例: prefecture, mesh2)。",
        ),
    ] = None,
) -> None:
    """カタログ内のデータセット一覧を表示する。"""
    catalog = _load_or_exit()

    matched = [
        (code, dataset, _collect_scopes(dataset))
        for code, dataset in catalog.datasets.items()
        if _category_matches(dataset, category)
        and (scope is None or scope in _collect_scopes(dataset))
    ]

    table = Table(title=f"KSJ カタログ ({len(catalog.datasets)} 件収録)")
    table.add_column("code", style="cyan", no_wrap=True)
    table.add_column("name")
    table.add_column("category", style="dim")
    table.add_column("versions", justify="right")
    table.add_column("scopes")

    for code, dataset, scopes in matched:
        table.add_row(
            code,
            dataset.name,
            dataset.category or "",
            str(len(dataset.versions)),
            ", ".join(scopes),
        )

    console.print(table)
    if not matched:
        err_console.print("[yellow]条件にマッチするデータセットはありません[/yellow]")


@app.command()
def info(
    code: Annotated[str, typer.Argument(help="データセットコード (例: N03)。")],
) -> None:
    """単一データセットの年度別 scope/CRS/形式分布を表示する。"""
    catalog = _load_or_exit()

    dataset = catalog.datasets.get(code)
    if dataset is None:
        err_console.print(f"[red]データセット '{code}' はカタログに存在しません[/red]")
        raise typer.Exit(code=1)

    console.print(f"[bold cyan]{code}[/bold cyan]  {dataset.name}")
    if dataset.category:
        console.print(f"  category:  {dataset.category}")
    if dataset.detail_page:
        console.print(f"  detail:    {dataset.detail_page}")
    if dataset.license:
        console.print(f"  license:   {dataset.license}")
    if dataset.notes:
        console.print(f"  notes:     {dataset.notes}")

    for year, version_entry in sorted(dataset.versions.items()):
        table = Table(title=f"[{year}]  files={len(version_entry.files)}", title_justify="left")
        table.add_column("scope", style="cyan")
        table.add_column("code", style="dim")
        table.add_column("crs", justify="right")
        table.add_column("format")
        table.add_column("url")

        for f in version_entry.files:
            table.add_row(
                f.scope,
                f.scope_identifier,
                str(f.crs) if f.crs is not None else "-",
                f.format,
                f.url,
            )
        console.print(table)


@catalog_app.command("refresh")
def catalog_refresh(
    only: Annotated[
        list[str] | None,
        typer.Option(
            "--only",
            help="指定データセットのみスクレイプする (複数指定可)。"
            " 他は既存カタログのまま保持される。",
        ),
    ] = None,
    parallel: Annotated[int, typer.Option("--parallel", help="ホスト別の同時接続数。")] = 2,
    rate: Annotated[
        float,
        typer.Option(
            "--rate",
            help="ホスト別の秒間リクエスト数上限 (レート制限)。",
        ),
    ] = 1.0,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="カタログ YAML を上書きせずサマリのみ表示。",
        ),
    ] = False,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache",
            help="HTML キャッシュを無視して KSJ サイトから再取得する。"
            " 取得した HTML はキャッシュに上書き保存される。",
        ),
    ] = False,
    cache_dir: Annotated[
        Path,
        typer.Option("--cache-dir", help="HTML キャッシュディレクトリ。"),
    ] = html_cache.DEFAULT_HTML_CACHE_DIR,
) -> None:
    """KSJ サイトを再スクレイプし catalog/datasets.yaml を更新する。

    デフォルトでは HTML キャッシュを優先し、ネットワーク負荷を避ける。
    """

    catalog, summary = _run_refresh(
        only=only,
        parallel=parallel,
        rate=rate,
        cache_dir=cache_dir,
        cache_policy=CachePolicy.OFF if no_cache else CachePolicy.READ_WRITE,
        status_message="スクレイピング中...",
    )

    console.print(
        f"[green]取得完了[/green]: {summary.total_datasets} データセット"
        f" (新規 {len(summary.added)} / 更新 {len(summary.updated)}"
        f" / 未変更保持 {len(summary.skipped)})"
    )
    _print_summary_warnings(summary)

    if dry_run:
        console.print("[dim]--dry-run のためファイル書き出しはスキップ[/dim]")
        return

    path = save_catalog(catalog)
    console.print(f"[green]書き出し[/green]: {path}")


@catalog_app.command("diff")
def catalog_diff() -> None:
    """同梱カタログ YAML と最新スクレイプ結果の差分を表示する。"""

    current = _load_or_exit()
    with console.status("[cyan]スクレイピング中...[/cyan]", spinner="dots"):
        fresh, _ = asyncio.run(refresh_catalog())

    diff = diff_catalogs(current, fresh)

    table = Table(title="catalog diff")
    table.add_column("kind", style="cyan")
    table.add_column("code")
    for code in diff.added:
        table.add_row("[green]added[/green]", code)
    for code in diff.removed:
        table.add_row("[red]removed[/red]", code)
    for code in diff.changed:
        table.add_row("[yellow]changed[/yellow]", code)
    console.print(table)

    if not (diff.added or diff.removed or diff.changed):
        console.print("[green]差分なし[/green]")


@html_app.command("fetch")
def html_fetch(
    only: Annotated[
        list[str] | None,
        typer.Option(
            "--only",
            help="指定データセットのみ取得 (複数指定可)。"
            " 省略時はトップ + 全 131 詳細ページを取得する。",
        ),
    ] = None,
    parallel: Annotated[int, typer.Option("--parallel", help="ホスト別の同時接続数。")] = 2,
    rate: Annotated[float, typer.Option("--rate", help="ホスト別の秒間リクエスト数上限。")] = 1.0,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="キャッシュ済みでも再取得して上書きする。",
        ),
    ] = False,
    cache_dir: Annotated[
        Path,
        typer.Option("--cache-dir", help="保存先ディレクトリ。"),
    ] = html_cache.DEFAULT_HTML_CACHE_DIR,
) -> None:
    """KSJ サイトの HTML を ``cache_dir`` に保存する (カタログ YAML は更新しない)。

    ``ksj catalog refresh`` は保存された HTML をそのまま使うので、初回実行後は
    オフラインでカタログ再生成できる。
    """

    _, summary = _run_refresh(
        only=only,
        parallel=parallel,
        rate=rate,
        cache_dir=cache_dir,
        cache_policy=CachePolicy.OFF if force else CachePolicy.READ_WRITE,
        status_message="HTML を取得中...",
    )

    stats = html_cache.summary(cache_dir)
    console.print(
        f"[green]HTML キャッシュ更新[/green]: {cache_dir} "
        f"(全 {stats.file_count} ファイル, {stats.total_mb:.1f} MB)"
    )
    _print_summary_warnings(summary)


@html_app.command("list")
def html_list(
    cache_dir: Annotated[
        Path,
        typer.Option("--cache-dir", help="キャッシュディレクトリ。"),
    ] = html_cache.DEFAULT_HTML_CACHE_DIR,
) -> None:
    """HTML キャッシュの内容を一覧表示する。"""

    entries = list(html_cache.iter_cached(cache_dir))
    if not entries:
        console.print(f"[yellow]キャッシュが空です: {cache_dir}[/yellow]")
        console.print("  [dim]ksj html fetch で取得してください[/dim]")
        return

    table = Table(title=f"HTML キャッシュ ({cache_dir})")
    table.add_column("path", style="cyan", no_wrap=False)
    table.add_column("size", justify="right")
    table.add_column("modified")
    total_bytes = 0
    for entry in entries:
        total_bytes += entry.size_bytes
        table.add_row(
            str(entry.path.relative_to(cache_dir)),
            f"{entry.size_bytes / 1024:.1f} KB",
            entry.modified_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)
    console.print(
        f"[green]合計[/green]: {len(entries)} ファイル / {total_bytes / (1024 * 1024):.1f} MB"
    )


# ---- download / ingest-local -----------------------------------------------


def _raw_dir(data_dir: Path, code: str, year: str) -> Path:
    return data_dir / "raw" / code / year


def _parse_format_preference(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass(slots=True)
class _DownloadPlan:
    """DL ターゲットと manifest 書き込みに必要なカタログメタのペア。"""

    target: DownloadTarget
    scope: str
    scope_identifier: str
    format: str


def _plans_from_catalog(
    catalog: Catalog,
    code: str,
    year: str,
    *,
    format_preference: list[str] | None,
    crs_filter: int | None,
    scope_filter: list[str] | None,
    prefer_national: bool,
    dest_root: Path,
) -> list[_DownloadPlan]:
    dataset = catalog.datasets.get(code)
    if dataset is None:
        err_console.print(f"[red]データセット '{code}' はカタログに存在しません[/red]")
        raise typer.Exit(code=1)
    if year not in dataset.versions:
        years = ", ".join(sorted(dataset.versions)) or "(登録なし)"
        err_console.print(f"[red]{code} に年度 {year} は存在しません[/red]  利用可能年度: {years}")
        raise typer.Exit(code=1)

    entries = pick_targets(
        dataset,
        year,
        format_preference=format_preference,
        crs_filter=crs_filter,
        scope_filter=scope_filter,
        prefer_national=prefer_national,
    )
    if not entries:
        err_console.print(
            f"[red]{code}/{year} で条件にマッチするファイルがありません[/red]"
            " (--crs / --format-preference / --scope を確認してください)"
        )
        raise typer.Exit(code=1)

    return [
        _DownloadPlan(
            target=DownloadTarget(
                url=f.url,
                dest_path=dest_root / filename_from_url(f.url),
                expected_size=f.size_bytes,
            ),
            scope=str(f.scope),
            scope_identifier=f.scope_identifier,
            format=str(f.format),
        )
        for f in entries
    ]


def _print_download_summary(results: list[DownloadResult]) -> None:
    done = [r for r in results if r.ok and not r.skipped]
    skipped = [r for r in results if r.skipped]
    failed = [r for r in results if not r.ok]
    total_bytes = sum(r.downloaded_bytes for r in done)
    console.print(
        f"[green]完了[/green]: 新規 {len(done)} / skip {len(skipped)} / 失敗 {len(failed)}"
        f"  (転送 {total_bytes / (1024 * 1024):.1f} MB)"
    )
    if failed:
        console.print("[yellow]失敗ファイル (再実行で再試行可能):[/yellow]")
        for r in failed[:10]:
            console.print(f"  {r.url} — {r.error}")
        if len(failed) > 10:
            console.print(f"  ...他 {len(failed) - 10} 件")


@app.command()
def download(
    code: Annotated[str, typer.Argument(help="データセットコード (例: N03)。")],
    year: Annotated[str, typer.Option("--year", help="取得対象年度 (例: 2025)。")],
    format_preference: Annotated[
        str | None,
        typer.Option(
            "--format-preference",
            help="複数形式が配布されている場合の優先順をカンマ区切りで指定"
            " (例: 'shp,geojson')。未指定なら全件取得。",
        ),
    ] = None,
    crs: Annotated[
        int | None,
        typer.Option("--crs", help="指定 EPSG コードのエントリのみ取得 (例: 6668)。"),
    ] = None,
    scope: Annotated[
        list[str] | None,
        typer.Option(
            "--scope",
            help="指定 scope のみ取得 (複数指定可。例: --scope national --scope region)。"
            " 語彙は catalog schema の Scope と同じ (national / prefecture / mesh1..6 等)。",
        ),
    ] = None,
    prefer_national: Annotated[
        bool,
        typer.Option(
            "--prefer-national",
            help="national scope があれば national のみ取得、無ければ全 scope を取得する"
            " (integrate の national 優先戦略と同等)。--scope と同時指定不可。",
        ),
    ] = False,
    data_dir: Annotated[Path, typer.Option("--data-dir", help="データ格納ルート。")] = Path("data"),
    parallel: Annotated[int, typer.Option("--parallel", help="ホスト別の同時接続数。")] = 2,
    rate: Annotated[float, typer.Option("--rate", help="ホスト別の秒間リクエスト上限。")] = 1.0,
) -> None:
    """カタログに記載された URL を並列ダウンロードする (Range レジューム対応)。"""

    if scope and prefer_national:
        err_console.print("[red]--scope と --prefer-national は同時指定できません[/red]")
        raise typer.Exit(code=1)

    catalog = _load_or_exit()
    # typer は --scope 未指定時に空 list を返す版と None を返す版があるので両方を
    # selector 側の「None=無効」シグネチャに揃える
    plans = _plans_from_catalog(
        catalog,
        code,
        year,
        format_preference=_parse_format_preference(format_preference),
        crs_filter=crs,
        scope_filter=scope or None,
        prefer_national=prefer_national,
        dest_root=_raw_dir(data_dir, code, year),
    )
    targets = [p.target for p in plans]

    console.print(
        f"[cyan]{code}/{year}[/cyan] の {len(targets)} ファイルをダウンロードします"
        f" (parallel={parallel}, rate={rate}/s)"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]ダウンロード中[/cyan]"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("files"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task_id = progress.add_task("download", total=len(targets))

        def _advance(_: DownloadResult) -> None:
            progress.advance(task_id)

        results = asyncio.run(
            download_many(
                targets,
                parallel=parallel,
                rate_per_sec=rate,
                on_file_done=_advance,
            )
        )

    manifest = load_manifest(data_dir)
    previous = {e.url: e for e in manifest.get_entries(code, year)}
    plan_by_url = {p.target.url: p for p in plans}
    now = datetime.now(UTC).replace(microsecond=0)
    merged: dict[str, ManifestEntry] = dict(previous)
    for result in results:
        if not result.ok:
            continue
        plan = plan_by_url[result.url]
        # skip は「前回取得した状態のまま」なので downloaded_at を更新しない
        downloaded_at = (
            previous[result.url].downloaded_at
            if (result.skipped and result.url in previous)
            else now
        )
        merged[result.url] = ManifestEntry(
            url=result.url,
            path=str(result.path.relative_to(data_dir)),
            size_bytes=result.path.stat().st_size,
            downloaded_at=downloaded_at,
            scope=plan.scope,
            scope_identifier=plan.scope_identifier,
            format=plan.format,
        )

    manifest.set_entries(code, year, list(merged.values()))
    save_manifest(manifest, data_dir)

    _print_download_summary(results)
    if all(not r.ok for r in results):
        raise typer.Exit(code=1)


@app.command("ingest-local")
def ingest_local(
    code: Annotated[str, typer.Argument(help="データセットコード (例: N03)。")],
    year: Annotated[str, typer.Option("--year", help="対象年度 (例: 2024)。")],
    source: Annotated[
        Path,
        typer.Option(
            "--from",
            help="取り込む ZIP ファイル、もしくは ZIP が入ったディレクトリ。",
        ),
    ],
    data_dir: Annotated[Path, typer.Option("--data-dir", help="データ格納ルート。")] = Path("data"),
) -> None:
    """ローカル ZIP を `data/raw/<code>/<year>/` に取り込む。"""

    if not source.exists():
        err_console.print(f"[red]--from で指定されたパスが見つかりません: {source}[/red]")
        raise typer.Exit(code=1)

    if source.is_dir():
        zips = sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() == ".zip")
    else:
        zips = [source]
    if not zips:
        err_console.print(f"[red]ZIP が見つかりません: {source}[/red]")
        raise typer.Exit(code=1)

    dest_root = _raw_dir(data_dir, code, year)
    dest_root.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(data_dir)
    existing = {e.url: e for e in manifest.get_entries(code, year)}
    now = datetime.now(UTC).replace(microsecond=0)
    copied: list[Path] = []
    for zip_path in zips:
        dest = dest_root / zip_path.name
        shutil.copy2(zip_path, dest)
        pseudo_url = f"{LOCAL_URL_PREFIX}{zip_path.resolve()}"
        existing[pseudo_url] = ManifestEntry(
            url=pseudo_url,
            path=str(dest.relative_to(data_dir)),
            size_bytes=dest.stat().st_size,
            downloaded_at=now,
        )
        copied.append(dest)

    manifest.set_entries(code, year, list(existing.values()))
    save_manifest(manifest, data_dir)

    console.print(f"[green]取り込み完了[/green]: {len(copied)} ファイル → {dest_root}")
    for dest in copied:
        console.print(f"  {dest.relative_to(data_dir)}")


# ---- integrate -------------------------------------------------------------


@app.command()
def integrate(
    code: Annotated[str, typer.Argument(help="データセットコード (例: N03)。")],
    year: Annotated[str, typer.Option("--year", help="対象年度 (例: 2025)。")],
    target_crs: Annotated[
        str,
        typer.Option(
            "--target-crs",
            help="出力 CRS (EPSG コード等、pyproj が解釈する任意の表現)。",
        ),
    ] = DEFAULT_TARGET_CRS,
    format_preference: Annotated[
        str | None,
        typer.Option(
            "--format-preference",
            help="ZIP 内に複数形式が同梱されているとき採用する優先順 (例: 'gml,shp,geojson')。"
            " 省略時は KSJ の 1 次配布である GML を最優先する。",
        ),
    ] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir", help="データ格納ルート。")] = Path("data"),
    strict_year: Annotated[
        bool,
        typer.Option(
            "--strict-year",
            help="対象年度と完全一致する識別子のみ採用 (latest-fill を無効化)。",
        ),
    ] = False,
    allow_partial: Annotated[
        bool,
        typer.Option(
            "--allow-partial",
            help="manifest に無いソースをスキップして続行する (警告のみ)。",
        ),
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help="出力先パス。省略時は data_dir/integrated/{code}-{year}.gpkg。",
        ),
    ] = None,
) -> None:
    """national / prefecture / mesh / urban_area / regional_bureau を GeoPackage に統合する。

    national があれば national 1 本で終了。無ければ scope + 識別子ごとに
    「対象年度以前で最新」を 1 件ずつ採用して union する (latest-fill)。
    --strict-year で年度完全一致のみに制限、--allow-partial で未取得ソースを
    無視して続行する。
    """

    catalog = _load_or_exit()
    try:
        with console.status(
            f"[cyan]{code}/{year} を統合中... (CRS={target_crs})[/cyan]",
            spinner="dots",
        ):
            result = integrate_dataset(
                catalog,
                code,
                year,
                data_dir=data_dir,
                target_crs=target_crs,
                format_preference=_parse_format_preference(format_preference),
                strict_year=strict_year,
                allow_partial=allow_partial,
                output_path=out,
            )
    except (
        KeyError,
        NoSourcesError,
        DownloadRequiredError,
        NoMatchingFormatError,
    ) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]統合完了[/green]: {result.output_path}")
    console.print(f"  strategy   : {result.strategy} (sources={result.source_count})")
    console.print(f"  target CRS : {result.target_crs} (converted={result.crs_converted})")
    console.print(f"  layers     : {', '.join(result.layer_names)}")
    if len(result.source_zips) == 1:
        console.print(f"  source ZIP : {result.source_zips[0]}")
    else:
        console.print(f"  source ZIPs: {len(result.source_zips)} files")
