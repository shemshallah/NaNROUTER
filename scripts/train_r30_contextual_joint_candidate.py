#!/usr/bin/env python3
"""R30 candidate-only contextual full-word joint learning from immutable 48M.

Updates existing R20 word unigram/bigram/trigram and R22 previous/pair-word
character tables on the SAME naturally occurring causal training positions.
No new model, no checkpoint/root/tensor promotion, no heldout-driven selection.
Prior R23 spelling background and exact R25 trie remain original and pinned.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, sys, time
from pathlib import Path
import numpy as np

ROOT=Path(os.environ.get('R29_ARCHIVE_ROOT',Path(__file__).resolve().parent)).resolve()
sys.path.insert(0,str(ROOT))
import train_r29_10epochs as r29
from train_r29_10epochs import r22,r22e,r23,r24,r25,ov
import ordered_gutenberg_v17 as r17
import hybrid_v20_emit as r20

PINS={'base':'299a91daf65c8e66fe3489940371d262afef18dd2ef6fef61947ac14c62bb717',
      'overlay':'62bf1e5defbb8224d795db16a8e6959cc9aa3d7fed8a63346c4cee205a1bea04',
      'train':'1f9eccda30366f40944a29dfc4ef073c77334526e773276e98ae21625ded4daf',
      'dev':'e185439debfef74f9aa2b0ae0f9f64e082e6674a6558c0aaf9c7386b1f8e4bb8',
      'test':'ab6035590b27082a1ba5293ea10c36f8f9f5b053aa96e27edc79218cceb74893'}
TOKEN_KEYS=('r11_vocab','r12_uni','r12_bi_idx','r12_bi_count','r12_tri_idx','r12_tri_count')

def read_token_state(base):
    with np.load(base,allow_pickle=False) as data:
        return {k:data[k].copy() for k in TOKEN_KEYS}

def sample_train(source,ids,limit):
    examples=[]
    for a,b,c,w,ok in r22.iter_valid_with_context(source,ids):
        if ok:
            examples.append((int(a),int(b),int(c),w))
            if len(examples)>=limit: break
    if len(examples)!=limit:raise ValueError('Not enough training occurrences')
    return examples

def count_character_additions(examples,base_counts,slots,hashes):
    delta=np.zeros_like(base_counts)
    events=0
    for a,b,c,w in examples:
        h=int(slots[b]);q=int(r22.pair_slot(a,b,hashes))
        for side,word in ((0,w),(1,w[::-1])):
            for j in range(len(word)+1):
                target=27 if j==len(word) else r22.ch(word[j])
                history=r22.charhist(word,j)
                delta[side,h,history,target]+=1
                delta[side,q,history,target]+=1
                events+=1
    assert int(delta.sum())==2*events
    return delta,events

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--train-words',type=int,default=40000)
    p.add_argument('--epochs',type=int,default=3)
    p.add_argument('--eval-words',type=int,default=128)
    p.add_argument('--output',type=Path,default=ROOT/'results_r30_contextual')
    a=p.parse_args()
    if not 1<=a.epochs<=10 or not 128<=a.train_words<=250000 or not 16<=a.eval_words<=2000:raise ValueError('Out of bounded research contract')
    t0=time.perf_counter()
    cfg=r29.init_args();a.output.mkdir(parents=True,exist_ok=True)
    paths={'base':cfg.base,'overlay':cfg.overlay,**{s:cfg.source/(s+'.txt') for s in ('train','dev','test')}}
    pins={k:r29.sha(v) for k,v in paths.items()}
    if pins!=PINS:raise ValueError('Original checkpoint/corpus SHA256 changed')
    vocab,spelling,base_direct,base_token=r23.load(cfg)
    ids={str(w):int(i) for i,w in enumerate(vocab)}
    oldstate=read_token_state(cfg.base)
    examples=sample_train(cfg.source/'train.txt',ids,a.train_words)
    samples=np.array([[x,y,z] for x,y,z,w in examples],dtype=np.int32)
    assert np.all(samples[:,2]>=0) and np.all(samples<len(vocab))
    delta,ntarget=count_character_additions(examples,base_direct.counts,base_direct.slots,base_direct.hashes)
    known,reverse,_=r23.mass_cache(spelling,vocab,cfg.old_cache,cfg.base,cfg.overlay)
    conf22=json.loads(cfg.r22_report.read_text())['development']['best']
    first2=r23.ExactFirst2(spelling,base_direct,known,reverse,conf22['alpha'],conf22['gamma'])
    conf23=json.loads(cfg.r23_report.read_text())['development_selection']
    conf24=json.loads(cfg.r24_report.read_text())['development_choice']
    trie=r24.VocabularyTrie.restore(cfg.trie,vocab,pins['base'],pins['overlay'])
    eta=float(conf24['full_context_mixture']);fw=float(conf23['forward_mix']);mix=float(conf23['prefix_context_mix'])
    def draw(split):
        batch,_=r23.sample_eval(cfg.source/(split+'.txt'),ids,a.eval_words,20261130)
        return [(int(x),int(y),w,int(ids.get(w,0))) for x,y,w,_ in batch]
    dev=draw('dev')
    def evaluate(items,direct,token):
        result=r25.score(items,r25.PairTrie(direct,trie,4.,.4,.1),spelling,first2,token,eta,fw,mix)
        # Report seen/novel target coverage to separate word-context from spelling.
        return result
    baseline=evaluate(dev,base_direct,base_token)
    print('R30_BASE',json.dumps(baseline),flush=True)
    counts=base_direct.counts.copy();state={k:v.copy() for k,v in oldstate.items()}
    assert int(counts.sum())==10000000
    results=[];credits=[];best={'epoch':0,'arm':'baseline','nll':baseline['true_word_nll_nats']}
    best_candidate=None
    for ep in range(1,a.epochs+1):
        tic=time.perf_counter()
        counts+=delta
        r17.update_token_counts(state,samples)
        update_sec=time.perf_counter()-tic
        direct=r22e.DirectChar(spelling,counts,base_direct.slots,base_direct.hashes)
        token=r20.AdaptiveTokenScorer(state)
        arms=[('context_char_only',direct,base_token),('context_token_only',base_direct,token),('joint_context',direct,token)]
        dev_by_arm={}
        for name,d,t in arms:
            start_eval=time.perf_counter()
            res=evaluate(dev,d,t)
            row={'epoch':ep,'arm':name,'train_wall_s':update_sec if name=='joint_context' else None,
                 'dev_exact_word_nll':res['true_word_nll_nats'],
                 'dev_ppl':res['true_word_perplexity'],
                 'dev_delta_vs_original':res['true_word_nll_nats']-baseline['true_word_nll_nats'],
                 'eval_wall_s':time.perf_counter()-start_eval}
            print('R30_ARM',json.dumps(row),flush=True);results.append(row)
            dev_by_arm[name]=row['dev_exact_word_nll']
            if row['dev_exact_word_nll']+1e-9<best['nll']:
                best={'epoch':ep,'arm':name,'nll':row['dev_exact_word_nll']}
                best_candidate={'counts':counts.copy() if name!='context_token_only' else None,
                                'state':{k:v.copy() for k,v in state.items()} if name!='context_char_only' else None}
        c=0.5*((baseline['true_word_nll_nats']-dev_by_arm['context_char_only'])
               +(dev_by_arm['context_token_only']-dev_by_arm['joint_context']))
        t=0.5*((baseline['true_word_nll_nats']-dev_by_arm['context_token_only'])
               +(dev_by_arm['context_char_only']-dev_by_arm['joint_context']))
        assert abs(c+t-(baseline['true_word_nll_nats']-dev_by_arm['joint_context']))<1e-9
        credit={'epoch':ep,'char_shapley_dev_gain_nats':c,'token_shapley_dev_gain_nats':t}
        print('R30_CONTEXT_CREDIT',json.dumps(credit),flush=True);credits.append(credit)
    # Only DEV selects; historical TEST is opened once after choosing.
    test=draw('test');original_test=evaluate(test,base_direct,base_token)
    if best_candidate is not None:
        candidate_direct=(r22e.DirectChar(spelling,best_candidate['counts'],base_direct.slots,base_direct.hashes)
                          if best_candidate['counts'] is not None else base_direct)
        candidate_token=(r20.AdaptiveTokenScorer(best_candidate['state'])
                         if best_candidate['state'] is not None else base_token)
        best_test=evaluate(test,candidate_direct,candidate_token)
    else: best_test=None
    report={'schema':'r30-contextual-joint-candidate/1','source':'original48m pinned R28; NaNROUTER corpora-short-stories TRAIN',
       'pins':pins,'train_eligible_positions_per_epoch':len(examples),'char_targets_per_epoch':ntarget,
       'token_context_events_per_epoch':len(samples),'epochs':a.epochs,'arms':results,'component_credit':credits,
       'baseline_dev':baseline,'development_selection':best,'original_test_readonly':original_test,
       'selected_joint_test_readonly':best_test,'full_run_s':time.perf_counter()-t0,
       'native_gradient_training':False,'native_word_gate_invoked':False,'promoted':False,
       'model_checkpoint_modified':False,'active_tensor_modified':False,
       'test_used_for_selection':False,
       'training_scope':'Real causal R20 known/OOV word uni/bi/tri tables and R22 forward/reverse preceding-word and pair-word character heads, same word events. No geometry/tensor write.'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    if best_candidate is not None:
        # Candidate-only compact delta; preserve immutable original base/overlay.
        fields={'original_base_sha256':np.array(pins['base']),
                'original_overlay_sha256':np.array(pins['overlay']),
                'best_epoch':np.array(best['epoch']), 'best_arm':np.array(best['arm'])}
        if best_candidate['counts'] is not None:
            fields['r22_context_character_counts']=best_candidate['counts']
        if best_candidate['state'] is not None:
            fields.update({k:v for k,v in best_candidate['state'].items() if k!='r11_vocab'})
        np.savez_compressed(a.output/'devselected_contextual_candidate.npz',**fields)
    if {k:r29.sha(v) for k,v in paths.items()}!=pins: raise AssertionError('Source was changed during training')
    print('R30_FINAL',json.dumps({'best':best,'baseline_dev':baseline,'original_test':original_test,'joint_test':best_test,'seconds':report['full_run_s']}),flush=True)
if __name__=='__main__':main()