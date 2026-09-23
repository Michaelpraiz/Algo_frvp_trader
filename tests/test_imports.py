import importlib
mods = [
    'mt5_mcp.tools.account_tools',
    'mt5_mcp.tools.market_tools',
    'mt5_mcp.tools.order_tools',
    'mt5_mcp.tools.analysis_tools',
    'mt5_mcp.tools.news_filter',
    'mt5_mcp.server',
]
errs=0
for m in mods:
    try:
        importlib.import_module(m)
        print('OK',m)
    except Exception as e:
        print('ERR',m,e)
        errs+=1
if errs:
    raise SystemExit(1)
print('SMOKE TEST COMPLETE')
