"""Read paginated Supabase research tables without a local dataset checkout."""

import argparse
import json
import os
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TABLES={"markets":"research_markets","trades":"research_trades","predictions":"research_predictions","wallets":"research_candidates"}


def query(kind, dataset=None, market=None, wallet=None, page_size=500):
    url=os.environ.get("SUPABASE_URL","").rstrip("/")
    key=os.environ.get("SUPABASE_PUBLISHABLE_KEY","")
    if not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co",url) or not key:
        raise ValueError("Set public Supabase URL and publishable key")
    if kind not in TABLES or not 1<=page_size<=1000:
        raise ValueError("Unsupported table/page size")
    params={"select":"*","limit":page_size}
    for name,value in (("dataset_key",dataset),("market_id",market),("wallet",wallet)):
        if value is not None:
            if not re.fullmatch(r"[a-zA-Z0-9_-]+",value):
                raise ValueError("Invalid filter")
            params[name]="eq."+value
    params["order"]={"markets":"dataset_key,market_id","trades":"dataset_key,market_id,source_row",
                     "predictions":"experiment_key,market_id,forecast_at,group_name,side","wallets":"experiment_key,activity_rank"}[kind]
    offset=0
    while True:
        request=Request(url+"/rest/v1/"+TABLES[kind]+"?"+urlencode({**params,"offset":offset}),headers={"apikey":key})
        with urlopen(request,timeout=30) as response:
            page=json.load(response)
        yield from page
        if len(page)<page_size:
            break
        offset+=len(page)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table",choices=TABLES)
    parser.add_argument("--dataset")
    parser.add_argument("--market")
    parser.add_argument("--wallet")
    args=parser.parse_args()
    for row in query(args.table,args.dataset,args.market,args.wallet):
        print(json.dumps(row))


if __name__ == "__main__":
    main()
