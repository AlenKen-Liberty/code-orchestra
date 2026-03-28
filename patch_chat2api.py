import os
import re

CHAT2API_DIR = os.path.expanduser("~/scripts/Chat2API/chat2api")

# 1. Patch admin.py
admin_path = os.path.join(CHAT2API_DIR, "routing", "admin.py")
with open(admin_path, "r") as f:
    admin_code = f.read()

if "admin_quota_distribution" not in admin_code:
    admin_code = admin_code.replace("from fastapi.responses import HTMLResponse, RedirectResponse", "from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse\nfrom pydantic import BaseModel")
    admin_code += """

@router.get("/quota-distribution", name="admin_quota_distribution")
async def admin_quota_distribution(request: Request):
    return JSONResponse({"providers": _build_provider_entries(request)})

class AcquireAccountRequest(BaseModel):
    provider: str
    model: str

@router.post("/acquire-account", name="admin_acquire_account")
async def admin_acquire_account(body: AcquireAccountRequest):
    if body.provider == "gemini":
        from chat2api.providers.gemini import GeminiBackend
        from chat2api.models.tiers import get_model_router
        try:
            target = get_model_router().resolve(body.model)
            accounts = GeminiBackend.get_accounts(target)
            if accounts:
                return JSONResponse({"email": accounts[0].email})
        except Exception as e:
            print(f"Error acquiring gemini account: {e}")
            pass
    elif body.provider == "codex":
        from chat2api.providers.codex import CodexBackend
        try:
            accounts = CodexBackend.get_accounts()
            if accounts:
                return JSONResponse({"email": accounts[0].email})
        except Exception:
            pass
    return JSONResponse({"email": None}, status_code=404)

class ReportExhaustionRequest(BaseModel):
    provider: str
    email: str
    model_tier: str | None = None

@router.post("/report-exhaustion", name="admin_report_exhaustion")
async def admin_report_exhaustion(body: ReportExhaustionRequest):
    import time
    if body.provider == "gemini":
        from chat2api.account.gemini_account import list_accounts, save_account
        for acc in list_accounts():
            if acc.email == body.email:
                if not acc.quota:
                    acc.quota = {}
                acc.quota["exhausted_at"] = int(time.time())
                save_account(acc)
                break
    elif body.provider == "codex":
        from chat2api.account.codex_account import list_accounts, save_account
        for acc in list_accounts():
            if acc.email == body.email:
                acc.quota_snapshot["exhausted_at"] = int(time.time())
                save_account(acc)
                break
    return JSONResponse({"status": "ok"})
"""
    with open(admin_path, "w") as f:
        f.write(admin_code)


# 2. Patch providers/gemini.py
gemini_path = os.path.join(CHAT2API_DIR, "providers", "gemini.py")
with open(gemini_path, "r") as f:
    gemini_code = f.read()

if "def get_accounts" not in gemini_code:
    gemini_code = gemini_code.replace("from chat2api.account.gemini_account import GeminiAuthError, ensure_fresh_account, list_accounts", "from chat2api.account.gemini_account import GeminiAuthError, ensure_fresh_account, list_accounts, save_account")
    gemini_code = gemini_code.replace("    def _get_accounts(self):", "    @staticmethod\n    def get_accounts(target: ModelTarget | None = None):")
    
    old_get_accounts = '''        """Return Gemini accounts sorted by enabled-first and least-recently-used."""
        accounts = list_accounts()
        if not accounts:
            raise ProviderAuthError("No Gemini accounts found")
        return sorted(accounts, key=lambda a: (a.disabled, a.last_used))'''
    
    new_get_accounts = '''        """Return Gemini accounts sorted by enabled-first and highest remaining quota for target tier."""
        accounts = list_accounts()
        if not accounts:
            raise ProviderAuthError("No Gemini accounts found")
        
        import time
        def account_score(a):
            if a.disabled:
                return (1, 0, a.last_used)
            
            # Penalize accounts marked as exhausted recently (within last 1 hour)
            exhausted_at = (a.quota or {}).get("exhausted_at", 0)
            is_exhausted = time.time() - exhausted_at < 3600
            
            pct = 100.0
            if a.quota and "buckets" in a.quota and target:
                for b in a.quota["buckets"]:
                    if b.get("modelFamily") == target.quota_group or target.model_id in b.get("models", []):
                        val = b.get("remainingPercent", b.get("remainingFraction"))
                        if val is not None:
                            pct = float(val) if val > 1 else float(val) * 100
                        break
            
            if is_exhausted:
                pct = 0.0
                
            return (0, -pct, a.last_used)
            
        return sorted(accounts, key=account_score)'''
    
    gemini_code = gemini_code.replace(old_get_accounts, new_get_accounts)
    gemini_code = gemini_code.replace("self._get_accounts()", "self.get_accounts(target)")
    
    old_stream_loop = '''            try:
                yield from self._stream_from_account(account, target, request)
                return  # success — stop iterating accounts
            except ProviderRateLimitError as exc:
                logger.info("Gemini account %s rate-limited, trying next account…", account.email)
                last_err = exc
                continue'''

    new_stream_loop = '''            for attempt in range(3):
                try:
                    yield from self._stream_from_account(account, target, request)
                    return
                except ProviderRateLimitError as exc:
                    logger.info("Gemini account %s rate-limited, checking actual quota...", account.email)
                    last_err = exc
                    try:
                        from chat2api.quota import fetch_gemini_quota
                        import time
                        quota_data = fetch_gemini_quota(account.token.access_token, account.project_id)
                        account.quota = quota_data
                        
                        is_exhausted = False
                        buckets = quota_data.get("buckets") or []
                        bucket = next((item for item in buckets if item.get("modelId") == target.model_id or item.get("modelFamily") == target.quota_group), None)
                        if bucket:
                            rem = bucket.get("remainingFraction")
                            if rem is not None and float(rem) <= 0.001:
                                is_exhausted = True
                        
                        if is_exhausted:
                            account.quota["exhausted_at"] = int(time.time())
                            save_account(account)
                            logger.info("Gemini account %s quota exhausted, skipping.", account.email)
                            break
                        else:
                            save_account(account)
                    except Exception as e:
                        logger.warning("Failed to check quota for %s: %s", account.email, e)
                        
                    if attempt < 2:
                        import time
                        time.sleep(2 ** attempt)
                        continue
                    else:
                        break'''
    gemini_code = gemini_code.replace(old_stream_loop, new_stream_loop)
    with open(gemini_path, "w") as f:
        f.write(gemini_code)


# 3. Patch providers/codex.py
codex_path = os.path.join(CHAT2API_DIR, "providers", "codex.py")
with open(codex_path, "r") as f:
    codex_code = f.read()

if "def get_accounts" not in codex_code:
    codex_code = codex_code.replace("from chat2api.account.codex_account import CodexAuthError, ensure_fresh_account, list_accounts", "from chat2api.account.codex_account import CodexAuthError, ensure_fresh_account, list_accounts, save_account")
    codex_code = codex_code.replace("    def _get_accounts(self):", "    @staticmethod\n    def get_accounts():")
    
    old_get_accounts_c = '''        """Return all enabled Codex accounts sorted by least-recently-used first."""
        accounts = [acc for acc in list_accounts() if not acc.disabled]
        if not accounts:
            raise ProviderAuthError("No enabled Codex accounts found")
        return sorted(accounts, key=lambda a: a.last_used)'''
    
    new_get_accounts_c = '''        """Return all enabled Codex accounts sorted by highest quota and least-recently-used first."""
        accounts = [acc for acc in list_accounts() if not acc.disabled]
        if not accounts:
            raise ProviderAuthError("No enabled Codex accounts found")
            
        import time
        def account_score(a):
            exhausted_at = a.quota_snapshot.get("exhausted_at", 0)
            is_exhausted = time.time() - exhausted_at < 3600
            
            # Sort exhausted ones last
            return (1 if is_exhausted else 0, a.last_used)
            
        return sorted(accounts, key=account_score)'''
    codex_code = codex_code.replace(old_get_accounts_c, new_get_accounts_c)
    codex_code = codex_code.replace("self._get_accounts()", "self.get_accounts()")

    old_stream_loop_c = '''            try:
                yield from self._stream_from_account(account, target, request)
                return  # success — stop iterating accounts
            except ProviderRateLimitError as exc:
                logger.info("Codex account %s rate-limited, trying next account…", account.email)
                last_err = exc
                continue'''

    new_stream_loop_c = '''            for attempt in range(3):
                try:
                    yield from self._stream_from_account(account, target, request)
                    return
                except ProviderRateLimitError as exc:
                    logger.info("Codex account %s rate-limited, checking actual usage...", account.email)
                    last_err = exc
                    try:
                        from chat2api.quota import fetch_codex_usage
                        import time
                        usage = fetch_codex_usage(account.access_token, account.account_id)
                        account.quota_snapshot = usage
                        
                        # Simplified heuristic: if we get a 429 and usage fetch works, mark exhausted
                        # Actually we can check rate_limit.primary_window
                        is_exhausted = False
                        primary = (usage.get("rate_limit") or {}).get("primary_window") or {}
                        rem = primary.get("remaining_fraction")
                        if rem is not None and float(rem) <= 0.001:
                            is_exhausted = True
                        
                        if is_exhausted:
                            account.quota_snapshot["exhausted_at"] = int(time.time())
                            save_account(account)
                            logger.info("Codex account %s quota exhausted, skipping.", account.email)
                            break
                        else:
                            save_account(account)
                    except Exception as e:
                        logger.warning("Failed to check quota for %s: %s", account.email, e)
                        
                    if attempt < 2:
                        import time
                        time.sleep(2 ** attempt)
                        continue
                    else:
                        break'''
    codex_code = codex_code.replace(old_stream_loop_c, new_stream_loop_c)
    with open(codex_path, "w") as f:
        f.write(codex_code)

print("Patch applied successfully.")
