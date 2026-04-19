"""rich 出力モードの整形実装。

既存 ``ksj.cli`` 内での ``console.print(Table)`` / メッセージ表示をここに移植する。
文言・色付けは現行挙動と 1:1 で保存し、CliRunner 経由の既存テストが壊れないよう
配慮する。
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from ksj.catalog.refresh import RefreshSummary
from ksj.errors import HandlerError
from ksj.handlers import (
    CatalogDiffResult,
    CatalogSummary,
    DatasetInfo,
    DownloadReport,
    HtmlFetchReport,
    HtmlListResult,
    IngestLocalReport,
    ListResult,
    RefreshReport,
)
from ksj.integrator.pipeline import IntegrateResult


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


def refresh_summary(
    report: RefreshReport,
    *,
    console: Console,
    dry_run: bool,
) -> None:
    s = report.summary
    console.print(
        f"[green]取得完了[/green]: {s.total_datasets} データセット"
        f" (新規 {len(s.added)} / 更新 {len(s.updated)}"
        f" / 未変更保持 {len(s.skipped)})"
    )
    _print_refresh_warnings(s, console=console)

    if dry_run:
        console.print("[dim]--dry-run のためファイル書き出しはスキップ[/dim]")
        return
    if report.saved_path is not None:
        console.print(f"[green]書き出し[/green]: {report.saved_path}")


def html_fetch_summary(report: HtmlFetchReport, *, console: Console) -> None:
    stats = report.cache_stats
    console.print(
        f"[green]HTML キャッシュ更新[/green]: {report.cache_dir} "
        f"(全 {stats.file_count} ファイル, {stats.total_mb:.1f} MB)"
    )
    _print_refresh_warnings(report.summary, console=console)


def _print_refresh_warnings(summary: RefreshSummary, *, console: Console) -> None:
    if summary.unsupported:
        console.print(
            f"[yellow]フォームベース配布 (自動 URL 取得不可)[/yellow]: "
            f"{', '.join(summary.unsupported)}"
        )
    if summary.warnings:
        console.print(f"[yellow]{len(summary.warnings)} 件の警告[/yellow] (先頭 3 件のみ):")
        for w in summary.warnings[:3]:
            console.print(f"  {w}")


def download_summary(report: DownloadReport, *, console: Console) -> None:
    total_bytes = report.downloaded_bytes
    console.print(
        f"[green]完了[/green]: 新規 {len(report.succeeded)}"
        f" / skip {len(report.skipped)} / 失敗 {len(report.failed)}"
        f"  (転送 {total_bytes / (1024 * 1024):.1f} MB)"
    )
    if report.failed:
        console.print("[yellow]失敗ファイル (再実行で再試行可能):[/yellow]")
        for r in report.failed[:10]:
            console.print(f"  {r.url} — {r.error}")
        if len(report.failed) > 10:
            console.print(f"  ...他 {len(report.failed) - 10} 件")


def ingest_local_summary(
    report: IngestLocalReport,
    *,
    console: Console,
    data_dir: Path,
) -> None:
    console.print(
        f"[green]取り込み完了[/green]: {len(report.copied)} ファイル → {report.dest_root}"
    )
    for dest in report.copied:
        console.print(f"  {dest.relative_to(data_dir)}")


def integrate_summary(result: IntegrateResult, *, console: Console) -> None:
    console.print(f"[green]統合完了[/green]: {result.output_path}")
    console.print(f"  strategy   : {result.strategy} (sources={result.source_count})")
    console.print(f"  target CRS : {result.target_crs} (converted={result.crs_converted})")
    console.print(f"  layers     : {', '.join(result.layer_names)}")
    if len(result.source_zips) == 1:
        console.print(f"  source ZIP : {result.source_zips[0]}")
    else:
        console.print(f"  source ZIPs: {len(result.source_zips)} files")


def catalog_summary(summary: CatalogSummary, *, console: Console) -> None:
    console.print(f"[bold cyan]KSJ カタログ[/bold cyan]  total={summary.total_datasets}")

    cat_table = Table(title="categories (count desc)")
    cat_table.add_column("category", style="cyan")
    cat_table.add_column("count", justify="right")
    for name, count in summary.categories.items():
        cat_table.add_row(name, str(count))
    console.print(cat_table)

    scope_table = Table(title="scope histogram (dataset 単位)")
    scope_table.add_column("scope", style="cyan")
    scope_table.add_column("count", justify="right")
    for scope, count in summary.scope_histogram.items():
        scope_table.add_row(scope, str(count))
    console.print(scope_table)

    if summary.years_seen:
        head, tail = summary.years_seen[:5], summary.years_seen[-5:]
        span = ", ".join(head)
        if len(summary.years_seen) > 10:
            span += f" ... {', '.join(tail)}"
        elif len(summary.years_seen) > 5:
            span = ", ".join(summary.years_seen)
        console.print(f"years seen: {len(summary.years_seen)} 年 ({span})")


def failure(error: HandlerError, *, err_console: Console) -> None:
    err_console.print(f"[red]{error.message}[/red]")
