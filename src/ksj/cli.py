from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ksj import __version__
from ksj.catalog import Catalog, Dataset, load_catalog
from ksj.catalog.loader import CatalogNotFoundError
from ksj.catalog.refresh import (
    diff_catalogs,
    refresh_catalog,
    save_catalog,
)

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
) -> None:
    """KSJ サイトを再スクレイプし catalog/datasets.yaml を更新する。"""

    with console.status("[cyan]スクレイピング中...[/cyan]", spinner="dots"):
        catalog, summary = asyncio.run(
            refresh_catalog(
                only=only,
                parallel=parallel,
                rate_per_sec=rate,
            )
        )

    console.print(
        f"[green]取得完了[/green]: {summary.total_datasets} データセット"
        f" (新規 {len(summary.added)} / 更新 {len(summary.updated)}"
        f" / 未変更保持 {len(summary.skipped)})"
    )
    if summary.unsupported:
        console.print(
            f"[yellow]フォームベース配布 (自動 URL 取得不可)[/yellow]: "
            f"{', '.join(summary.unsupported)}"
        )
    if summary.warnings:
        console.print(f"[yellow]{len(summary.warnings)} 件の警告 (先頭 3 件のみ表示):[/yellow]")
        for w in summary.warnings[:3]:
            console.print(f"  {w}")

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
