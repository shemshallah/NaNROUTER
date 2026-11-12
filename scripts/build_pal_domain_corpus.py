#!/usr/bin/env python3
"""Build PAL-compatible, domain-balanced Gutenberg splits from NaNROUTER releases.

Input: Project Gutenberg pg_catalog.csv plus NaNROUTER corpora/*.tar.zst assets.
Streaming extraction, whole-book/author-disjoint splits, SHA256 checks, and
exclusion of historical PAL book IDs. Does not modify any model checkpoint.
"""
import argparse, csv, hashlib, json, pathlib, re, subprocess, tarfile
from collections import Counter

DOMAINS=('medicine','science_technology','law_politics','economics_society',
         'philosophy_religion','history_geography','literature')

def digest(v): return hashlib.sha256(v).hexdigest()

def domain_of(row):
    subjects=(row.get('Subjects') or '').lower()
    shelves=(row.get('Bookshelves') or '').lower()
    locc=(row.get('LoCC') or '').upper()
    prefix={x[:1] for x in re.findall(r'\b[A-Z]{1,3}\b',locc)}
    blob=subjects+' '+shelves
    if 'R' in prefix or re.search(r'\b(medicine|medical|physiology|anatomy)\b',blob): return 'medicine'
    if prefix & {'Q','T'} or re.search(r'\b(physics|chemistry|mathematics|biology|engineering|astronomy|science)\b',blob): return 'science_technology'
    if prefix & {'J','K'} or re.search(r'\b(law|government|political science|politics)\b',blob): return 'law_politics'
    if 'H' in prefix or re.search(r'\b(economics|economy|sociology|commerce)\b',blob): return 'economics_society'
    if 'B' in prefix or re.search(r'\b(philosophy|ethics|religion|theology)\b',blob): return 'philosophy_religion'
    if prefix & {'D','E','F','G'} or re.search(r'\b(history|geography|exploration)\b',blob): return 'history_geography'
    if 'P' in prefix or re.search(r'\b(fiction|novel|poetry|literature|drama|short stories)\b',blob): return 'literature'
    return None

def catalog(path):
    out={}
    with open(path,'r',encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            bid=(row.get('Text#') or row.get('Text #') or row.get('EBook-No.') or '').strip()
            if not bid.isdigit(): continue
            if not ('en' in (row.get('Language') or '').lower() or 'english' in (row.get('Language') or '').lower()): continue
            dom=domain_of(row)
            if dom:
                out[str(int(bid))]={'domain':dom,'author':row.get('Authors') or '',
                                   'title':row.get('Title') or ''}
    return out

def historical(manifests):
    ids=set(); hashes=set()
    for m in manifests:
        d=json.loads(pathlib.Path(m).read_text())
        for row in d.get('documents',[]):
            ids.add(str(row.get('gutenberg_id')))
            if row.get('sha256'): hashes.add(row['sha256'])
    return ids,hashes

def stream_archive(archive):
    archive=pathlib.Path(archive)
    if archive.suffix=='.zst':
        proc=subprocess.Popen(['zstd','-dc','--',str(archive)],stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=proc.stdout,mode='r|') as tar:
                for member in tar:
                    if member.isfile() and member.name.endswith('.txt'):
                        yield member,tar.extractfile(member)
        finally:
            proc.stdout.close()
            if proc.wait(): raise RuntimeError('zstd decompression failed: '+str(archive))
    else:
        with tarfile.open(archive,mode='r|*') as tar:
            for member in tar:
                if member.isfile() and member.name.endswith('.txt'):
                    yield member,tar.extractfile(member)

def run(args):
    info=catalog(args.catalog)
    if not info: raise ValueError('no English Gutenberg books with usable catalog topics')
    excluded_ids,excluded_sha=historical(args.exclude_manifest)
    candidates={d:[] for d in DOMAINS}
    for bid,row in info.items():
        if bid not in excluded_ids: candidates[row['domain']].append(bid)
    selected={}
    for dom,ids in candidates.items():
        ids.sort(key=lambda x:digest(f'PAL-R13-domain-v1:{args.seed}:{x}'.encode()))
        for bid in ids[:args.max_per_domain]: selected[bid]=dom
    out=pathlib.Path(args.output);out.mkdir(parents=True,exist_ok=True)
    seen_hash=set(excluded_sha);seen_normalized=set();found={};skips=Counter()
    for archive in args.archive:
        for member,stream in stream_archive(archive):
            name=pathlib.PurePosixPath(member.name).name
            m=re.match(r'^(\d+)(?:--|\.txt$)',name)
            if not m: continue
            bid=str(int(m.group(1)))
            if bid not in selected or bid in found: continue
            if member.size>args.max_book_bytes or member.size<args.min_book_bytes:
                skips['book_size']+=1;continue
            raw=stream.read(args.max_book_bytes+1)
            if len(raw)!=member.size: raise ValueError('truncated tar member: '+member.name)
            raw.decode('utf-8','strict')
            h=digest(raw); norm=digest(b' '.join(raw.lower().split()))
            if h in seen_hash or norm in seen_normalized:
                skips['duplicate_content']+=1;continue
            seen_hash.add(h);seen_normalized.add(norm)
            row=info[bid]
            author=(row['author'].strip().lower() or 'unknown:'+bid)
            bucket=int(digest(f'PAL-R13-heldout-v1:{args.seed}:{author}'.encode())[:8],16)%100
            split='test' if bucket<10 else ('dev' if bucket<20 else 'train')
            path=out/split/(bid+'.txt');path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(raw)
            found[bid]={'gutenberg_id':bid,'split':split,'sha256':h,'bytes':len(raw),
                        'domain':selected[bid],'author':row['author'],'title':row['title'],
                        'source_archive':pathlib.Path(archive).name,'source_tar_member':member.name}
    docs=sorted(found.values(),key=lambda r:(r['split'],r['domain'],int(r['gutenberg_id'])))
    if not docs: raise ValueError('no usable books extracted; check catalog and release batches')
    report={'source_repository':'shemshallah/NaNROUTER','source_policy':'published corpora/* releases only',
            'split_policy':'SHA256(PAL-R13-heldout-v1:seed:author) mod 100: 80 train, 10 dev, 10 test',
            'split_caveat':'Historical contamination not fully excluded without all predecessor corpora and similarity scan',
            'archives':[str(p) for p in args.archive],
            'counts_by_split':dict(Counter(r['split'] for r in docs)),
            'counts_by_domain':dict(Counter(r['domain'] for r in docs)),
            'skipped':dict(skips),'documents':docs}
    (out/'MANIFEST.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'books':len(docs),'splits':report['counts_by_split'],
                      'domains':report['counts_by_domain'],'output':str(out)},indent=2))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--catalog',required=True)
    p.add_argument('--archive',required=True,action='append')
    p.add_argument('--exclude-manifest',action='append',default=[])
    p.add_argument('--output',required=True);p.add_argument('--max-per-domain',type=int,default=500)
    p.add_argument('--min-book-bytes',type=int,default=1000)
    p.add_argument('--max-book-bytes',type=int,default=12000000)
    p.add_argument('--seed',type=int,default=20261111)
    run(p.parse_args())
