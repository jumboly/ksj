from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
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
from ksj.html_cache import CachePolicy

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


@app.callback()
def _main() -> None:
    """Typer がサブコマンド構造になるよう明示的なコールバックを置く。"""


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
    table.add_column("coverage", justify="center")

    for code, dataset, scopes in matched:
        coverage_cell = (
            "[green]full[/green]" if dataset.coverage == "full" else "[yellow]partial[/yellow]"
        )
        table.add_row(
            code,
            dataset.name,
            dataset.category or "",
            str(len(dataset.versions)),
            ", ".join(scopes),
            coverage_cell,
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
    console.print(f"  coverage:  {dataset.coverage}")
    if dataset.coverage_notes:
        console.print(f"    note:    {dataset.coverage_notes}")
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
