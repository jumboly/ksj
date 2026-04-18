from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ksj import __version__
from ksj.catalog import Catalog, Dataset, load_catalog
from ksj.catalog.loader import CatalogNotFoundError

app = typer.Typer(
    name="ksj",
    help="国土数値情報 (KSJ) のカタログ管理・ダウンロード・統合 CLI",
    no_args_is_help=True,
    add_completion=False,
)

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
