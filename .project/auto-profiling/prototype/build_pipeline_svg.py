"""Generate ../pipeline.svg (the architecture flowchart) with Lucide icons.

Usage: npm pack lucide-static@0.460.0 && tar xzf lucide-static-0.460.0.tgz
       python build_pipeline_svg.py package/icons ../pipeline.svg
"""
import sys
ICONS, OUT = sys.argv[1], sys.argv[2]
import re
def icon(name,x,y,color,size=22):
    s=open(f"{ICONS}/{name}.svg").read()
    inner=re.search(r'<svg[^>]*>(.*)</svg>',s,re.S).group(1).strip()
    inner=re.sub(r'\s+',' ',inner)
    return f'<g transform="translate({x:.1f},{y:.1f}) scale({size/24:.4f})" fill="none" stroke="{color}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">{inner}</g>'
W=720; cx=W/2; bw=500; bx=cx-bw/2
GF="#F6F5F1"; GS="#B4B2A9"; T1="#2C2C2A"; T2="#5F5E5A"
TF="#E1F5EE"; TS="#5DCAA5"; TT="#085041"; TT2="#0F6E56"
out=[]; y=24; h=56
def step(ic,title,sub):
    global y
    out.append(f'<rect x="{bx}" y="{y}" width="{bw}" height="{h}" rx="12" fill="{GF}" stroke="{GS}" stroke-width="0.75"/>')
    out.append(icon(ic,bx+18,y+17,T2))
    out.append(f'<text x="{bx+56}" y="{y+24}" font-size="14" font-weight="600" fill="{T1}">{title}</text>')
    out.append(f'<text x="{bx+56}" y="{y+42}" font-size="12" fill="{T2}">{sub}</text>')
    y+=h
def arrow(g=30):
    global y
    out.append(f'<line x1="{cx}" y1="{y+2}" x2="{cx}" y2="{y+g-4}" stroke="#888780" stroke-width="1" marker-end="url(#a)"/>'); y+=g
step("database","Select distributions","SPARQL on opendata.swiss, dataset IRIs from datasets.txt"); arrow()
step("scan-search","Detect real format","libmagic + content rules (Tika optional)"); arrow()
step("download","Fetch sample","HEAD, range request, ZIP directory, WFS count"); arrow()
out.append(f'<text x="{cx}" y="{y+8}" font-size="12" fill="{T2}" text-anchor="middle">Infer structure, by format family</text>'); y+=18
cw=680; cl=cx-cw/2; ch=96
out.append(f'<rect x="{cl}" y="{y}" width="{cw}" height="{ch}" rx="12" fill="none" stroke="{GS}" stroke-width="0.75" stroke-dasharray="4 3"/>')
chips=[("table-2","Tabular","DuckDB, Frictionless"),("map","Geo","DuckDB spatial"),("share-2","RDF","sheXer"),("boxes","PX","pyaxis"),("braces","JSON / XML","genson, XSD, lxml")]
n=len(chips); gp=10; pw=(cw-20-gp*(n-1))/n
for i,(ic,t,s) in enumerate(chips):
    px=cl+10+i*(pw+gp); py=y+10
    out.append(f'<rect x="{px:.1f}" y="{py}" width="{pw:.1f}" height="{ch-20}" rx="8" fill="{TF}" stroke="{TS}" stroke-width="0.75"/>')
    out.append(icon(ic,px+pw/2-11,py+10,TT2))
    out.append(f'<text x="{px+pw/2:.1f}" y="{py+50}" font-size="13" font-weight="600" fill="{TT}" text-anchor="middle">{t}</text>')
    out.append(f'<text x="{px+pw/2:.1f}" y="{py+66}" font-size="11" fill="{TT2}" text-anchor="middle">{s}</text>')
y+=ch; arrow()
step("git-merge","Normalise","Profile JSON, a superset of Frictionless Table Schema"); arrow()
step("shapes","Map to SHACL","sh:NodeShape + prof:observed, cube:Constraint where clear"); arrow()
step("cloud-upload","Publish","out/auto-profiling.ttl, imported by hand into visoto-qlever")
H=int(y+24)
head=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Segoe UI, Helvetica, Arial, sans-serif">',
'<title>auto-profiling pipeline</title>',
'<!-- Icons: Lucide v0.460.0 (ISC license), https://lucide.dev -->',
'<defs><marker id="a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M2 1L8 5L2 9" fill="none" stroke="#888780" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>',
f'<rect width="{W}" height="{H}" rx="12" fill="#FFFFFF"/>']
open(OUT, "w").write("\n".join(head+out)+"\n</svg>\n")
