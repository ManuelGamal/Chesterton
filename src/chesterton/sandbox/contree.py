"""Real SandboxRunner backed by Nebius Token Factory Sandboxes (ConTree).

Verified against `contree-sdk` 0.3.6 by offline introspection on 2026-09-18.
An earlier version of this file was written from the plan's assumptions and was
wrong in three places — it imported a `contree_client` package that does not
exist, passed a client object to a constructor that takes `base_url`/`token`,
and treated `.uuid` as a string. None of that could be caught by the shape-only
tests, which is why the SDK surface is now pinned by a real-construction test.

Surface this file depends on (all confirmed present in 0.3.6):

    Contree(config=None, *, base_url=None, token=None)
        .images -> ImagesManager
    ImagesManager.use(ref: str | UUID | OCIReference, strict: bool = False)
    ImagesManager.oci(ref, *, tag=None, username=None, password=None, timeout=None)
    ContreeImage.run(command=None, *, shell=None, files=None, env=None, cwd=None,
                     tag=None, timeout=None, disposable=True, ...) -> ContreeImage
        .stdout .stderr .exit_code .elapsed .state  (properties)
        .uuid  -> uuid.UUID   (instance attribute, NOT a str)
    contree_sdk.sdk.exceptions.ContreeError
        base of FailedOperationError, CancelledOperationError and
        OperationTimedOutError, which `await image.run(...)` raises

Two shapes worth knowing. `run()` returns another `ContreeImage`, not a result
object — the image *is* the checkpoint, so runs chain. And `ContreeImage` is
awaitable (`__await__`), which is what makes `await image.run(...)` work even
though `run` is not itself a coroutine function.

One trap worth knowing. `run(files=...)` takes `{image_path: source}`, and in
`UploadFileSpec._prepare_files` a `str` source is a LOCAL FILE PATH — it is
wrapped in `Path(...)` and opened. Only `bytes` is uploaded as content. Our
callers hold file *contents* as text (a mutant's `mutated_src`), so passing
them straight through would ask the SDK to open a file whose name is the
source code. `_as_upload` encodes at this boundary so nothing else has to know.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from chesterton.paths import normalise_path
from chesterton.sandbox.protocol import RunResult

#: Trailing slash matches ContreeEndpoint.TOKEN_FACTORY_SANDBOXES.
DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/sandboxes/"

#: The SDK's own sentinels. `Auth.resolve()` substitutes a field whose value
#: names an environment variable, and keeps any other value as a literal — so
#: these round-trip to the real credentials when the env vars are set.
_ENV_TOKEN = "NEBIUS_API_KEY"
_ENV_PROJECT = "NEBIUS_PROJECT_ID"

_MISSING_SDK = (
    "contree-sdk is not installed. Install the sandbox extra with "
    'pip install -e ".[sandbox]" before using ConTreeSandboxRunner.'
)

_MISSING_PROJECT = (
    "No Nebius project id. Sandboxes authorises on a Project header as well as "
    "a bearer token, and a request without one is rejected as ForbiddenError — "
    "which looks like a permissions problem but is a configuration one. Set "
    f"{_ENV_PROJECT}, or pass project_id=..., using the id from "
    "https://tokenfactory.nebius.com/project/api-keys"
)


def _as_upload(files: Mapping[str, str | bytes]) -> dict[str, bytes]:
    """File contents in the only form the SDK uploads as contents: bytes.

    Destination keys are image paths, which the SDK builds with
    `PurePosixPath`; a backslash there is not a separator but part of one flat
    filename, so keys are normalised to forward slashes too.
    """
    upload: dict[str, bytes] = {}
    for destination, content in files.items():
        if isinstance(content, str):
            content = content.encode("utf-8")
        elif not isinstance(content, bytes):
            # A Path here would be uploaded as a local file — the very
            # confusion this function exists to rule out.
            raise TypeError(
                f"file contents for {destination!r} must be str or bytes, "
                f"not {type(content).__name__}"
            )
        key = normalise_path(destination)
        if key in upload:
            raise ValueError(f"two destinations normalise to {key!r}")
        upload[key] = content
    return upload


class ConTreeSandboxRunner:
    """Sandboxes needs BOTH a bearer token and a project id.

    Inference on Token Factory needs only the key, so a key that works fine for
    `/v1/chat/completions` still fails here. The failure is a bare 403 with no
    hint about the missing project, so this class checks for it up front.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        project_id: str | None = None,
    ) -> None:
        # Falling back to the sentinel names lets the SDK resolve both from the
        # environment, which is the path the official quickstart documents.
        self.api_key = api_key or _ENV_TOKEN
        self.project_id = project_id or _ENV_PROJECT
        self.base_url = base_url
        self._sdk = None

    def _handle(self):
        """The Contree client, built on first use.

        Lazy so that importing this module — and running every test that only
        checks its shape — does not require the sandbox extra.
        """
        if self._sdk is None:
            try:
                from contree_sdk import Contree
                from contree_sdk.auth import IAMAuth
                from contree_sdk.config import ContreeConfig
            except ImportError as exc:  # fail loudly, at first use, with a fix
                raise RuntimeError(_MISSING_SDK) from exc

            if self.project_id == _ENV_PROJECT and not os.environ.get(_ENV_PROJECT):
                raise RuntimeError(_MISSING_PROJECT)

            # Built explicitly rather than via Contree(base_url=, token=),
            # because that constructor exposes no project_id and the default
            # would go out as the literal string "NEBIUS_PROJECT_ID".
            auth = IAMAuth(
                token=self.api_key,
                project_id=self.project_id,
                base_url=self.base_url,
            )
            self._sdk = Contree(ContreeConfig(auth=auth))
        return self._sdk

    async def use_image(self, ref: str) -> str:
        sdk = self._handle()
        if ref.startswith("docker://"):
            image = await sdk.images.oci(ref)
        else:
            # strict=True forces a real resolution. Without it `use()` returns
            # a LAZY handle whose .uuid is None — and str(None) is the truthy
            # string "None", which sails past any caller that merely checks
            # for a non-empty id. Fail here instead, where the cause is legible.
            image = await sdk.images.use(ref, strict=True)

        if image.uuid is None:
            raise RuntimeError(
                f"image {ref!r} did not resolve to a checkpoint id — the handle "
                "came back unresolved, which usually means the reference is "
                "wrong or the account cannot read it."
            )
        # .uuid is a uuid.UUID; the protocol promises a str.
        return str(image.uuid)

    async def run(
        self,
        checkpoint_id: str,
        shell: str,
        *,
        files: Mapping[str, str | bytes] | None = None,
        disposable: bool = True,
        tag: str | None = None,
        timeout: float | None = None,
    ) -> RunResult:
        sdk = self._handle()
        from contree_sdk.sdk.exceptions import ContreeError

        image = await sdk.images.use(checkpoint_id)
        try:
            result = await image.run(
                shell=shell,
                files=_as_upload(files) if files else None,
                disposable=disposable,
                tag=tag,
                timeout=timeout,
            )
        except ContreeError as exc:
            # A failed, cancelled or timed-out operation. The SDK marks the
            # image FAILED and re-raises, so a FAILED image never comes back
            # from run() — the exception is the only signal there is. It is
            # an error, never a pass and never a kill. Only the SDK's own
            # errors are caught: a bug in this code must still surface.
            return RunResult(
                stdout="",
                stderr="",
                exit_code=None,
                checkpoint_id=None,
                duration_s=None,
                error=f"{type(exc).__name__}: {exc}",
            )
        # Reaching here, the image is SUCCEEDED and its result properties are
        # safe to read. A command that exited non-zero lands here too, as an
        # ordinary result: measured live 2026-09-19, `exit 1` returned
        # SUCCEEDED with exit_code=1, while a timeout raised
        # OperationTimedOutError.
        #
        # A disposable run persists nothing, so there is no id to fork from.
        # Reporting result.uuid here would let offline code depend on
        # something the fake cannot honestly provide.
        return RunResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            checkpoint_id=None if disposable else str(result.uuid),
            duration_s=result.elapsed.total_seconds(),
        )

    async def aclose(self) -> None:
        """No-op against contree-sdk 0.3.6, which exposes no close/aclose.

        Kept because the protocol declares it and a future SDK may acquire
        one — consumers should not have to learn which implementation needs
        closing.
        """
        self._sdk = None
