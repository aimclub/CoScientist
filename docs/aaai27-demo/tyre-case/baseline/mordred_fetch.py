"""Step 1 of the mordred trial: descriptors of cure-system and protective
ingredients from the Alembic server (tool descriptors_from_smiles). Needs mcp + boto3."""
import asyncio, json, re, sys
from pathlib import Path
import boto3
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

HERE = Path(__file__).resolve().parent
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:21988/mcp"
SMILES = {
    "CBS": "C1CCC(CC1)NSC2=NC3=CC=CC=C3S2",
    "TBBS": "CC(C)(C)NSC1=NC2=CC=CC=C2S1",
    "DCBS": "C1CCC(CC1)N(C2CCCCC2)SC3=NC4=CC=CC=C4S3",
    "MBT": "SC1=NC2=CC=CC=C2S1",
    "MBTS": "C1=CC=C2C(=C1)N=C(S2)SSC3=NC4=CC=CC=C4S3",
    "DPG": "C1=CC=C(C=C1)NC(=N)NC2=CC=CC=C2",
    "TMTD": "CN(C)C(=S)SSC(=S)N(C)C",
    "ZnMBT": "C1=CC=C2C(=C1)N=C(S2)[S-].C1=CC=C2C(=C1)N=C(S2)[S-].[Zn+2]",
    "6PPD": "CC(C)CC(C)NC1=CC=C(C=C1)NC2=CC=CC=C2",
    "IPPD": "CC(C)NC1=CC=C(C=C1)NC2=CC=CC=C2",
    "TMQ": "CC1=CC(C)(C)NC2=CC=CC=C12",
    "TESPT": "CCO[Si](CCCSSSSCCC[Si](OCC)(OCC)OCC)(OCC)OCC",
    "TESPD": "CCO[Si](CCCSSCCC[Si](OCC)(OCC)OCC)(OCC)OCC",
    "NXT": "CCCCCCCC(=O)SCCC[Si](OCC)(OCC)OCC",
}


async def main():
    env = dict(re.match(r"^([A-Z0-9_]+)=(.*)$", l.rstrip("\n")).groups()
               for l in open(HERE.parents[3] / ".env") if re.match(r"^[A-Z0-9_]+=", l))
    s3 = boto3.client("s3", endpoint_url="http://127.0.0.1:19000",
                      aws_access_key_id=env["S3__ACCESS_KEY"], aws_secret_access_key=env["S3__SECRET_KEY"])
    async with streamablehttp_client(URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tool = next(t for t in (await s.list_tools()).tools if t.name == "descriptors_from_smiles")
            print("schema", {k: v.get("type") for k, v in tool.inputSchema["properties"].items()})
            res = await s.call_tool("descriptors_from_smiles", {"smiles": list(SMILES.values())})
            d = json.loads(res.content[0].text)
            if d.get("result_s3"):
                ref = d["result_s3"]
                d = json.loads(s3.get_object(Bucket=ref["bucket"], Key=ref["s3_key"])["Body"].read())
            json.dump({"names": list(SMILES), "result": d}, open(HERE / "mordred_raw.json", "w"))
            print("keys", list(d)[:8])

asyncio.run(main())
