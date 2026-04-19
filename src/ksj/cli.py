from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

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

from ksj import __version__, handlers, html_cache
from ksj.downloader import DownloadResult
from ksj.errors import HandlerError
from ksj.html_cache import CachePolicy
from ksj.integrator import DEFAULT_TARGET_CRS
from ksj.renderers import OutputFormat, json_render, rich_render

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


@dataclass(slots=True)
class _CLIState:
    """root callback で決まる実行全体の出力モード。"""

    format: OutputFormat


def _get_format(ctx: typer.Context) -> OutputFormat:
    state = ctx.obj
    assert isinstance(state, _CLIState)
    return state.format


def _render_failure(fmt: OutputFormat, exc: HandlerError) -> None:
    if fmt is OutputFormat.JSON:
        json_render.failure(exc)
    else:
        rich_render.failure(exc, err_console=err_console)


@app.callback()
def _main(
    ctx: typer.Context,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help="JSON 出力モード (--format json と等価、同時指定時はこちらを優先)。",
        ),
    ] = False,
    output_format: Annotated[
        OutputFormat,
        typer.Option(
            "--format",
            help="出力形式。rich (デフォルト、人間向け表組) または json (機械可読)。",
            case_sensitive=False,
        ),
    ] = OutputFormat.RICH,
) -> None:
    """Typer がサブコマンド構造になるよう明示的なコールバックを置く。"""
    _configure_logging()
    # --json 指定時は --format より優先する。両方同時指定時の警告は出さず、
    # JSON 契約は docs/json-output.md に明記する。
    ctx.obj = _CLIState(format=OutputFormat.JSON if json_mode else output_format)


@app.command()
def version() -> None:
    """バージョンを表示する。"""
    typer.echo(__version__)


@app.command("list")
def list_datasets(
    ctx: typer.Context,
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
    fmt = _get_format(ctx)
    try:
        result = handlers.list_datasets_data(category=category, scope=scope)
    except HandlerError as exc:
        _render_failure(fmt, exc)
        raise typer.Exit(code=exc.exit_code) from exc

    if fmt is OutputFormat.JSON:
        json_render.success("list", result)
    else:
        rich_render.list_datasets(result, console=console, err_console=err_console)


@app.command()
def info(
    ctx: typer.Context,
    code: Annotated[str, typer.Argument(help="データセットコード (例: N03)。")],
) -> None:
    """単一データセットの年度別 scope/CRS/形式分布を表示する。"""
    fmt = _get_format(ctx)
    try:
        result = handlers.dataset_info_data(code)
    except HandlerError as exc:
        _render_failure(fmt, exc)
        raise typer.Exit(code=exc.exit_code) from exc

    if fmt is OutputFormat.JSON:
        json_render.success("info", result)
    else:
        rich_render.dataset_info(result, console=console)


@catalog_app.command("refresh")
def catalog_refresh(
    ctx: typer.Context,
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
    fmt = _get_format(ctx)
    policy = CachePolicy.OFF if no_cache else CachePolicy.READ_WRITE

    def _run() -> Any:
        return handlers.catalog_refresh_data(
            only=only,
            parallel=parallel,
            rate=rate,
            cache_dir=cache_dir,
            cache_policy=policy,
            dry_run=dry_run,
        )

    try:
        if fmt is OutputFormat.RICH:
            with console.status("[cyan]スクレイピング中...[/cyan]", spinner="dots"):
                report = _run()
        else:
            report = _run()
    except HandlerError as exc:
        _render_failure(fmt, exc)
        raise typer.Exit(code=exc.exit_code) from exc

    if fmt is OutputFormat.JSON:
        json_render.success("catalog.refresh", report)
    else:
        rich_render.refresh_summary(report, console=console, dry_run=dry_run)


@catalog_app.command("diff")
def catalog_diff(ctx: typer.Context) -> None:
    """同梱カタログ YAML と最新スクレイプ結果の差分を表示する。"""
    fmt = _get_format(ctx)
    try:
        # rich モードではネットワーク待ちを spinner で見せる。JSON では UI を出さない。
        if fmt is OutputFormat.RICH:
            with console.status("[cyan]スクレイピング中...[/cyan]", spinner="dots"):
                diff = handlers.catalog_diff_data()
        else:
            diff = handlers.catalog_diff_data()
    except HandlerError as exc:
        _render_failure(fmt, exc)
        raise typer.Exit(code=exc.exit_code) from exc

    if fmt is OutputFormat.JSON:
        json_render.success("catalog.diff", diff)
    else:
        rich_render.catalog_diff(diff, console=console)


@html_app.command("fetch")
def html_fetch(
    ctx: typer.Context,
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
    fmt = _get_format(ctx)
    policy = CachePolicy.OFF if force else CachePolicy.READ_WRITE

    def _run() -> Any:
        return handlers.html_fetch_data(
            only=only,
            parallel=parallel,
            rate=rate,
            cache_dir=cache_dir,
            cache_policy=policy,
        )

    try:
        if fmt is OutputFormat.RICH:
            with console.status("[cyan]HTML を取得中...[/cyan]", spinner="dots"):
                report = _run()
        else:
            report = _run()
    except HandlerError as exc:
        _render_failure(fmt, exc)
        raise typer.Exit(code=exc.exit_code) from exc

    if fmt is OutputFormat.JSON:
        json_render.success("html.fetch", report)
    else:
        rich_render.html_fetch_summary(report, console=console)


@html_app.command("list")
def html_list(
    ctx: typer.Context,
    cache_dir: Annotated[
        Path,
        typer.Option("--cache-dir", help="キャッシュディレクトリ。"),
    ] = html_cache.DEFAULT_HTML_CACHE_DIR,
) -> None:
    """HTML キャッシュの内容を一覧表示する。"""
    fmt = _get_format(ctx)
    result = handlers.html_list_data(cache_dir=cache_dir)

    if fmt is OutputFormat.JSON:
        json_render.success("html.list", result)
    else:
        rich_render.html_list(result, console=console)


# ---- download / ingest-local -----------------------------------------------


def _parse_format_preference(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


@app.command()
def download(
    ctx: typer.Context,
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
    fmt = _get_format(ctx)

    try:
        if fmt is OutputFormat.RICH:
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
                task_id = progress.add_task("download", total=0)

                def _on_start(count: int) -> None:
                    progress.update(task_id, total=count)
                    console.print(
                        f"[cyan]{code}/{year}[/cyan] の {count} ファイルをダウンロードします"
                        f" (parallel={parallel}, rate={rate}/s)"
                    )

                def _on_done(_: DownloadResult) -> None:
                    progress.advance(task_id)

                report = handlers.download_data(
                    code,
                    year,
                    data_dir=data_dir,
                    format_preference=_parse_format_preference(format_preference),
                    crs_filter=crs,
                    scope_filter=scope or None,
                    prefer_national=prefer_national,
                    parallel=parallel,
                    rate=rate,
                    on_start=_on_start,
                    progress=_on_done,
                )
        else:
            report = handlers.download_data(
                code,
                year,
                data_dir=data_dir,
                format_preference=_parse_format_preference(format_preference),
                crs_filter=crs,
                scope_filter=scope or None,
                prefer_national=prefer_national,
                parallel=parallel,
                rate=rate,
            )
    except HandlerError as exc:
        _render_failure(fmt, exc)
        raise typer.Exit(code=exc.exit_code) from exc

    if fmt is OutputFormat.JSON:
        json_render.success("download", report)
    else:
        rich_render.download_summary(report, console=console)

    if report.all_failed:
        raise typer.Exit(code=1)


@app.command("ingest-local")
def ingest_local(
    ctx: typer.Context,
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
    fmt = _get_format(ctx)
    try:
        report = handlers.ingest_local_data(
            code,
            year,
            source=source,
            data_dir=data_dir,
        )
    except HandlerError as exc:
        _render_failure(fmt, exc)
        raise typer.Exit(code=exc.exit_code) from exc

    if fmt is OutputFormat.JSON:
        json_render.success("ingest-local", report)
    else:
        rich_render.ingest_local_summary(report, console=console, data_dir=data_dir)


# ---- integrate -------------------------------------------------------------


@app.command()
def integrate(
    ctx: typer.Context,
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
    fmt = _get_format(ctx)

    def _run() -> Any:
        return handlers.integrate_data(
            code,
            year,
            data_dir=data_dir,
            target_crs=target_crs,
            format_preference=_parse_format_preference(format_preference),
            strict_year=strict_year,
            allow_partial=allow_partial,
            output_path=out,
        )

    try:
        if fmt is OutputFormat.RICH:
            with console.status(
                f"[cyan]{code}/{year} を統合中... (CRS={target_crs})[/cyan]",
                spinner="dots",
            ):
                result = _run()
        else:
            result = _run()
    except HandlerError as exc:
        _render_failure(fmt, exc)
        raise typer.Exit(code=exc.exit_code) from exc

    if fmt is OutputFormat.JSON:
        json_render.success("integrate", result)
    else:
        rich_render.integrate_summary(result, console=console)


@catalog_app.command("summary")
def catalog_summary_cmd(ctx: typer.Context) -> None:
    """カタログ全体のメタ集計 (categories / scope_histogram / years_seen) を表示する。"""
    fmt = _get_format(ctx)
    try:
        summary = handlers.catalog_summary_data()
    except HandlerError as exc:
        _render_failure(fmt, exc)
        raise typer.Exit(code=exc.exit_code) from exc

    if fmt is OutputFormat.JSON:
        json_render.success("catalog.summary", summary)
    else:
        rich_render.catalog_summary(summary, console=console)
