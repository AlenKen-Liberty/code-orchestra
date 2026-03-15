import sys
from models.google.account import get_active_email, list_accounts, set_active_account
from models.google.oauth import ensure_fresh_token
from models.google.quota import fetch_account_quota

# Dynamically load all registered accounts
TARGET_EMAILS = [acc.email for acc in list_accounts()]

TARGET_MODEL = "gemini-3.1-pro-preview"
IDE_TYPE = "GEMINI_CLI"

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"

def show_dashboard():
    print(f"\n  {C.BOLD}📊 Gemini CLI 3.1 Pro Preview Quotas{C.RESET}")
    print(f"{'=' * 50}\n")
    
    active_email = get_active_email()
    accounts = {acc.email: acc for acc in list_accounts()}
    
    for email in TARGET_EMAILS:
        is_active = (email == active_email)
        prefix = f"{C.CYAN}→ ACTIVE{C.RESET}" if is_active else "        "
        print(f"  {prefix} {C.BOLD}{email}{C.RESET}")
        
        acc = accounts.get(email)
        if not acc:
            print(f"      {C.RED}Account not logged in.{C.RESET}\n")
            continue
            
        if acc.disabled:
             print(f"      {C.RED}Account DISABLED.{C.RESET}\n")
             continue
             
        try:
            acc.token = ensure_fresh_token(acc.token)
        except Exception as e:
            print(f"      {C.RED}Token Invalid ({e}).{C.RESET}\n")
            continue
            
        try:
            quota, new_pid = fetch_account_quota(acc.token.access_token, cached_project_id=acc.project_id, ide_type=IDE_TYPE)
            if new_pid and new_pid != acc.project_id:
                from models.google.account import save_account
                acc.project_id = new_pid
                save_account(acc)
                
            if quota.is_forbidden:
                print(f"      {C.RED}⛔ Account forbidden (403){C.RESET}\n")
                continue
                
            model_quota = None
            for mq in quota.models:
                if mq.family == "Gemini 3.1 Pro Preview":
                    if not model_quota or mq.percentage < model_quota.percentage:
                        model_quota = mq
                    
            if not model_quota:
                print(f"      {C.DIM}No quota data found for {TARGET_MODEL}.{C.RESET}\n")
                continue
                
            fraction = model_quota.percentage
            status = f"{C.GREEN}{fraction}% remaining{C.RESET}" if fraction > 0 else f"{C.RED}EXHAUSTED{C.RESET}"
            print(f"      {TARGET_MODEL}: {status}")
            
        except Exception as e:
            print(f"      {C.RED}Error fetching quota: {e}{C.RESET}")
            
        print()

def switch_user(email: str):
    if email not in TARGET_EMAILS:
        print(f"  {C.YELLOW}Warning: {email} is not in the currently registered accounts.{C.RESET}")
        
    if set_active_account(email):
        print(f"\n  {C.GREEN}✅ Switched active account to {email} for Gemini CLI.{C.RESET}\n")
    else:
        print(f"\n  {C.RED}❌ Account '{email}' not found. Please login first.{C.RESET}\n")


def rotate_user(threshold: int = 40):
    print(f"\n  {C.BOLD}🔄 Auto-Rotating Gemini CLI Account (Threshold: {threshold}%){C.RESET}")
    print(f"{'=' * 60}\n")
    
    active_email = get_active_email()
    accounts = {acc.email: acc for acc in list_accounts()}
    
    candidates = []
    active_quota = None
    
    for email in TARGET_EMAILS:
        acc = accounts.get(email)
        if not acc or acc.disabled:
            continue
            
        try:
            acc.token = ensure_fresh_token(acc.token)
        except:
            continue
            
        try:
            quota, new_pid = fetch_account_quota(acc.token.access_token, cached_project_id=acc.project_id, ide_type=IDE_TYPE)
            if new_pid and new_pid != acc.project_id:
                from models.google.account import save_account
                acc.project_id = new_pid
                save_account(acc)
                
            if quota.is_forbidden:
                continue
                
            model_quota = None
            for mq in quota.models:
                if mq.family == "Gemini 3.1 Pro Preview":
                    if not model_quota or mq.percentage < model_quota.percentage:
                        model_quota = mq
            
            fraction = model_quota.percentage if model_quota else 0
            
            if email == active_email:
                active_quota = fraction
            
            candidates.append((email, fraction))
            
        except Exception:
            continue
            
    if not candidates:
        print(f"  {C.RED}No eligible accounts found to check quota.{C.RESET}")
        return
        
    # Check if we need to rotate
    if active_quota is not None and active_quota >= threshold:
        print(f"  {C.GREEN}✅ Current active account ({active_email}) has {active_quota}% remaining. No rotation needed.{C.RESET}\n")
        return
        
    print(f"  {C.YELLOW}⚠ Current account has {active_quota}% remaining (Below {threshold}%). Sorting candidates...{C.RESET}")
    
    # Sort candidates by remaining fraction descending
    candidates.sort(key=lambda x: x[1], reverse=True)
    best_email, best_fraction = candidates[0]
    
    if best_fraction == 0:
        print(f"  {C.RED}⛔ All accounts are exhausted (0% remaining).{C.RESET}\n")
        return
        
    print(f"  {C.CYAN}→ Selected {best_email} with {best_fraction}% remaining.{C.RESET}")
    switch_user(best_email)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "dashboard" or cmd == "status":
            show_dashboard()
        elif cmd == "switch":
            if len(sys.argv) < 3:
                print(f"  {C.RED}Usage: python gemini_dashboard.py switch <email>{C.RESET}")
            else:
                switch_user(sys.argv[2])
        elif cmd == "rotate":
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument("cmd")
            parser.add_argument("--threshold", type=int, default=40)
            args, _ = parser.parse_known_args(sys.argv[1:])
            rotate_user(args.threshold)
        else:
            print(f"  {C.RED}Unknown command: {cmd}{C.RESET}")
    else:
        show_dashboard()
