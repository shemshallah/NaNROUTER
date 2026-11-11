#!/usr/bin/env python3
"""R28 original 48M R25 whole-word readout for an external NaN16 candidate.

IMPORT CONTRACT: add the user's original R27 experiment_archive/ to PYTHONPATH
before importing this module. It extends, DOES NOT REPLACE, the original
pair_context_trie_v25.PairTrie and trained R22 DirectChar. No training or
parameter search; candidate weight comes from the native feedback contract.

A single T[ord(prefix0)-97, ord(prefix1)-97, ord(target)-97] value
tilts one character logit at every matching causal two-character prefix.
For each prefix with predicted class t and original p(t):
   p'(s) = p(s)*exp(theta*[s=t]) / (1+p(t)*expm1(theta)).
The known-vocabulary trie DP applies the same factor to every branch and
EOS, then subtracts exact known-word mass. Therefore known tokens retain
their ORIGINAL token probabilities and OOV tokens are normalized properly.
"""
from __future__ import annotations
import math
import numpy as np
import pair_context_trie_v25 as r25
import open_vocab_v21 as ov

class MirrorWordReadout(r25.PairTrie):
    def __init__(self,direct,trie,alpha=4.,gamma=.4,pair_weight=.1,
                 prefix="th",target="e",theta=0.,coordinate=(19,7,4)):
        super().__init__(direct,trie,alpha,gamma,pair_weight)
        if (len(prefix)!=2 or not prefix.isascii() or not prefix.islower()
            or any(not "a"<=c<="z" for c in prefix)):
            raise ValueError("Two natural lowercase letter history required")
        if len(target)!=1 or not "a"<=target<="z":
            raise ValueError("One natural target character required")
        coord=tuple(ord(c)-97 for c in prefix+target)
        if tuple(coordinate)!=coord:
            raise ValueError("Mirror tensor coordinate is symbol ID, not ASCII")
        if not math.isfinite(theta) or abs(theta)>1:
            raise ValueError("Unbounded nonfinite mirror tensor weight")
        self.prefix,self.target,self.theta=prefix,target,float(theta)
        self.tclass=coord[2]
        self.hist_index=coord[0]*28+coord[1]
        self.exp_theta=math.exp(theta)
        self.expm1_theta=math.expm1(theta)
        self.selected=np.flatnonzero(trie.hist==self.hist_index)
        self._base_target=None
        self._tilt_cache={}

    def _base_target_at_selected(self):
        if self._base_target is not None:return self._base_target
        tr=self.trie
        result=np.empty(len(self.selected),dtype=np.float64)
        for k,node in enumerate(self.selected):
            parts=[];i=int(node)
            while i:
                letter=int(tr.syms[i])
                parts.append("'" if letter==26 else chr(letter+97))
                i=int(tr.parents[i])
            prefix="".join(reversed(parts))
            if not prefix.endswith(self.prefix):
                raise AssertionError("Trie context mismatch")
            # Target may be absent as an EXPLICIT child, but it remains
            # a valid unseen spelling. Never assume its probability is zero.
            result[k]=self.direct.base_dist(prefix,0)[self.tclass]
        self._base_target=result
        return result

    def known_mass(self,a,b):
        key=(int(a),int(b),self.theta,self.alpha,self.gamma,self.pair_weight)
        if key in self._tilt_cache:return self._tilt_cache[key]
        if self.theta==0:
            v=super().known_mass(a,b)
            self._tilt_cache[key]=v
            return v
        tr=self.trie
        h,q=self.keys(a,b)
        r1,r2,cb,c1,c2,grammar_denom=self._coefficients(h,q)
        p_t=(cb[self.hist_index]*self._base_target_at_selected()+
             c1[self.hist_index]*r1[self.hist_index,self.tclass]+
             c2[self.hist_index]*r2[self.hist_index,self.tclass])
        if np.any(p_t<0) or np.any(p_t>1+1e-9):
            raise AssertionError("Bad original character distribution")
        denom=np.ones(tr.n,dtype=np.float64)
        denom[self.selected]=1+self.expm1_theta*p_t
        if np.any(denom<=0):raise AssertionError("Bad conditional normalizer")

        # EXACT original R25 shared-prefix DP with target logit tilt.
        weight=np.zeros(tr.n,dtype=np.float64)
        weight[0]=1
        for nodes in tr.by_depth:
            parents=tr.parents[nodes]
            history=tr.hist[parents]
            symbol=tr.syms[nodes].astype(np.int32)
            edge=(cb[history]*tr._base_edge[nodes-1]+
                  c1[history]*r1[history,symbol]+
                  c2[history]*r2[history,symbol])
            edge/=np.where(tr._invalid[parents],grammar_denom[history],1.)
            factor=np.where((history==self.hist_index)&
                            (symbol==self.tclass),self.exp_theta,1.)
            edge*=factor/denom[parents]
            weight[nodes]=weight[parents]*edge
        term=tr.terminal;history=tr.hist[term]
        eos=(cb[history]*tr._base_end+
             c1[history]*r1[history,27]+c2[history]*r2[history,27])
        eos/=np.where(tr._invalid[term],grammar_denom[history],1.)
        # Target is a letter, not EOS; EOS still undergoes renormalization.
        eos/=denom[term]
        mass=float(np.dot(weight[term],eos))
        if not 0<=mass<1:raise AssertionError("Invalid exact known-word mass")
        self._tilt_cache[key]=mass
        return mass

    def logp(self,word,a,b):
        if not ov.VALID.fullmatch(word):return -math.inf
        p=self.direct.logp(word,(int(a),int(b)),0,
                           self.alpha,self.gamma,self.pair_weight)
        if self.theta==0:return p
        change=0.
        for j in range(2,len(word)+1):
            if word[j-2:j]!=self.prefix:continue
            distribution=self.direct.step(word[:j],(int(a),int(b)),0,
                                          self.alpha,self.gamma,self.pair_weight)
            pt=float(distribution[self.tclass])
            emitted=27 if j==len(word) else (26 if word[j]=="'" else ord(word[j])-97)
            change+=(self.theta if emitted==self.tclass else 0.)-math.log1p(
                      self.expm1_theta*pt)
        return p+change

    def probability(self,word,a,b):
        if not ov.VALID.fullmatch(word):return 0.
        value=math.exp(self.logp(word,a,b))/(1.-self.known_mass(a,b))
        if not 0<=value<=1+1e-8:
            raise AssertionError("Bad OOV conditional probability")
        return value
