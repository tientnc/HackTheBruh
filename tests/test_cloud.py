import base64
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from polyresearch.cloud import Supabase, apply, normalized_trades
from polyresearch.dataset import table
from polyresearch.demo import export


class CloudTests(unittest.TestCase):
    def test_trade_import_flags_takers_without_dropping_identical_legitimate_fills(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            trade={"timestamp":"50","wallet":"a","side":"BUY","outcome":"Yes","token_id":"yes",
                   "size_shares":"10","price":"0.5","transaction_hash":"same-hash"}
            maker={**trade,"wallet":"b","side":"SELL"}
            table(root/"market/trades.csv.gz",[trade,trade],list(trade))
            table(root/"market/wallet_trade_legs.csv.gz",[trade,maker,trade,maker],list(trade))
            result=list(normalized_trades(root,{"folder":"market","market_id":"1"}))
            self.assertEqual(len(result),4)
            self.assertEqual(sum(r["is_taker"] for r in result),2)
            self.assertEqual([r["source_row"] for r in result],[1,2,3,4])
            table(root/"market/wallet_trade_legs.csv.gz",[maker],list(trade))
            with self.assertRaises(ValueError):
                list(normalized_trades(root,{"folder":"market","market_id":"1"}))

    def test_admin_import_rejects_public_key_and_untrusted_endpoint(self):
        segment=base64.urlsafe_b64encode(json.dumps({"role":"anon"}).encode()).decode().rstrip("=")
        for key in ("sb_publishable_example",f"header.{segment}.signature"):
            with self.assertRaises(ValueError):
                Supabase("https://example.supabase.co",key)
        with self.assertRaises(ValueError):
            Supabase("https://another.example","sb_secret_example")

    def test_server_count_check_does_not_download_trade_rows(self):
        client=Supabase("https://example.supabase.co","sb_secret_example")
        with patch.object(client,"request",return_value={"Content-Range":"0-999/376683"}) as request:
            self.assertEqual(client.count("research_trades"),376683)
            self.assertEqual(request.call_args.args[0],"HEAD")
            self.assertTrue(request.call_args.kwargs["headers_only"])

    def test_snapshot_conflict_is_rejected_before_upload_or_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'plan.json').write_text('{"tables":{}}')
            (root/'research_datasets.jsonl').write_text(json.dumps({'dataset_key':'one','source_sha256':'local'})+'\n')
            client=Mock()
            client.request.return_value=[{'source_sha256':'different','status':'ready'}]
            with self.assertRaisesRegex(ValueError,'differs'):
                apply(root,client)
            self.assertEqual(client.request.call_count,1)
            self.assertEqual(client.request.call_args.args[0],'GET')
            client.upsert.assert_not_called()

    def test_failed_server_verification_cannot_publish_partial_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            tables=['research_datasets','research_wallets','research_markets','research_trades','research_prices',
                    'research_returns','research_experiments','research_candidates','research_predictions','research_artifacts']
            data={name:[] for name in tables}
            data['research_datasets']=[{'dataset_key':'finance-2025-v1','source_sha256':'one','status':'loading'}]
            data['research_experiments']=[{'experiment_key':'participation-2026-01-v1','source_sha256':'one','status':'loading'}]
            for name,records in data.items():
                (root/(name+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in records))
            (root/'plan.json').write_text(json.dumps({'tables':{name:len(records) for name,records in data.items()}}))
            client=Mock()
            client.request.return_value=[]
            client.count.side_effect=lambda name: 1 if name=='research_trades' else len(data[name])
            with contextlib.redirect_stdout(io.StringIO()),self.assertRaisesRegex(ValueError,'count mismatch'):
                apply(root,client)
            self.assertFalse(any(call.args[0]=='PATCH' for call in client.request.call_args_list))

    def test_preview_exports_real_counts_and_no_full_trade_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            result=export(Path(temporary)/"snapshot.json")
            self.assertEqual(len(result["markets"]),120)
            self.assertEqual(len(result["predictions"]),120)
            self.assertEqual(len(result["candidates"]),100)
            self.assertNotIn("trades",result)

    def test_build_never_publishes_import_key_and_rejects_admin_as_public_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            env={**os.environ,"DEMO_BUILD_DIRECTORY":temporary,"SUPABASE_SERVICE_ROLE_KEY":"DO_NOT_PUBLISH_THIS_IMPORT_SECRET",
                 "SUPABASE_URL":"","SUPABASE_PUBLISHABLE_KEY":""}
            result=subprocess.run(["node","scripts/build-demo.mjs"],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotIn("DO_NOT_PUBLISH",(Path(temporary)/"config.json").read_text())
            env.update(SUPABASE_URL="https://example.supabase.co",SUPABASE_PUBLISHABLE_KEY="sb_secret_wrong")
            result=subprocess.run(["node","scripts/build-demo.mjs"],env=env,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)


if __name__ == "__main__":
    unittest.main()
