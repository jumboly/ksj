"""rich 出力モードの整形実装。

既存 ``ksj.cli`` 内での ``console.print(Table)`` / メッセージ表示をここに移植する。
文言・色付けは現行挙動と 1:1 で保存し、CliRunner 経由の既存テストが壊れないよう
配慮する。
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from ksj.errors import HandlerError
from ksj.handlers import (
    CatalogDiffResult,
    DatasetInfo,
    HtmlListResult,
    ListResult,
)


def list_datasets(result: ListResult, *, console: Console, err_console: Console) -> None:
    table = Table(title=f"KSJ カタログ ({result.total} 件収録)")
    table.add_column("code", style="cyan", no_wrap=True)
    table.add_column("name")
    table.add_column("category", style="dim")
    table.add_column("versions", justify="right")
    table.add_column("scopes")

    for row in result.rows:
        table.add_row(
            row.code,
            row.name,
            row.category or "",
            str(row.versions),
            ", ".join(row.scopes),
        )

    console.print(table)
    if not result.rows:
        err_console.print("[yellow]条件にマッチするデータセットはありません[/yellow]")


def dataset_info(info: DatasetInfo, *, console: Console) -> None:
    console.print(f"[bold cyan]{info.code}[/bold cyan]  {info.name}")
    if info.category:
        console.print(f"  category:  {info.category}")
    if info.detail_page:
        console.print(f"  detail:    {info.detail_page}")
    if info.license:
        console.print(f"  license:   {info.license}")
    if info.notes:
        console.print(f"  notes:     {info.notes}")

    for version in info.versions:
        table = Table(
            title=f"[{version.year}]  files={len(version.files)}",
            title_justify="left",
        )
        table.add_column("scope", style="cyan")
        table.add_column("code", style="dim")
        table.add_column("crs", justify="right")
        table.add_column("format")
        table.add_column("url")

        for f in version.files:
            table.add_row(
                f.scope,
                f.scope_identifier,
                str(f.crs) if f.crs is not None else "-",
                f.format,
                f.url,
            )
        console.print(table)


def catalog_diff(diff: CatalogDiffResult, *, console: Console) -> None:
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

    if diff.is_empty:
        console.print("[green]差分なし[/green]")


def html_list(result: HtmlListResult, *, console: Console) -> None:
    if result.is_empty:
        console.print(f"[yellow]キャッシュが空です: {result.cache_dir}[/yellow]")
        console.print("  [dim]ksj html fetch で取得してください[/dim]")
        return

    table = Table(title=f"HTML キャッシュ ({result.cache_dir})")
    table.add_column("path", style="cyan", no_wrap=False)
    table.add_column("size", justify="right")
    table.add_column("modified")
    for entry in result.entries:
        table.add_row(
            entry.relative_path,
            f"{entry.size_bytes / 1024:.1f} KB",
            entry.modified_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)
    console.print(
        f"[green]合計[/green]: {len(result.entries)} ファイル"
        f" / {result.total_bytes / (1024 * 1024):.1f} MB"
    )


def failure(error: HandlerError, *, err_console: Console) -> None:
    err_console.print(f"[red]{error.message}[/red]")
