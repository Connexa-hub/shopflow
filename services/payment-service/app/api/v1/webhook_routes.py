"""
Webhook endpoints — deliberately NOT behind the platform's JWT auth.
Providers call these directly with no bearer token at all; trust is
established per-provider via HMAC signature verification inside
PaymentService.handle_webhook, not via anything in core/security.py.

Critical detail: every route here reads `await request.body()` for the
RAW bytes and passes those straight through, never `await request.json()`.
Signature verification is computed over the exact bytes the provider
transmitted — re-serializing a parsed dict back to JSON can differ in key
order or whitespace from the original transmission, which would silently
break every signature check. See paystack.py's module docstring, which
calls this out as a common real-world mistake.
"""
from fastapi import APIRouter, HTTPException, Request, status

from app.core.dependencies import PaymentServiceDep
from app.domain.models import PaymentProvider
from app.services.payment_service import InvalidWebhookError, PaymentValidationError

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post("/{provider}", status_code=status.HTTP_200_OK)
async def receive_webhook(
    provider: PaymentProvider, request: Request, payment_service: PaymentServiceDep
) -> dict[str, str]:
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    try:
        await payment_service.handle_webhook(provider=provider, headers=headers, raw_body=raw_body)
    except PaymentValidationError as exc:
        # The provider named in the URL path isn't configured on this
        # deployment (see get_provider_registry) — a deployment error or a
        # stray webhook pointed at the wrong environment, not a signature
        # problem, so this is a distinct 400 rather than folded into the
        # 401 case below.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InvalidWebhookError as exc:
        # 401, not 400 — signature/parse failures here are almost always
        # either a forged request or a misconfigured secret, and several
        # providers' own docs recommend treating this distinctly from a
        # generic bad request so it's easier to spot in provider-side
        # delivery logs.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    # Every provider's docs are explicit that anything other than a 200
    # triggers a retry — always return 200 once the event is durably
    # recorded, even if there was nothing further to do with it (e.g. no
    # matching local transaction), so a provider doesn't retry forever on
    # a payload we've already logged.
    return {"status": "received"}
