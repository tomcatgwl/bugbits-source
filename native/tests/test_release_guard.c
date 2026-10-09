/* SPDX-License-Identifier: MIT */
#include <stdio.h>
#include <string.h>
#include "release_guard.h"
static unsigned checks,failures;
static void check(int ok,const char *name) {
    checks++;if(!ok){failures++;fprintf(stderr,"FAIL: %s\n",name);}
}
int main(int argc,char **argv) {
    int negative=argc==2&&!strcmp(argv[1],"--negative-expected");
    if(argc>1&&!negative){fprintf(stderr,"Unknown option\n");return 2;}
    NRGState g;nrg_init(&g);
    check(nrg_quiet_live(&g),"fresh metadata is quiet");
    check(nrg_enter(&g)&&!nrg_quiet_live(&g),"in-flight call prevents quiet");
    check(!nrg_leave(&g,1)&&nrg_quiet_live(&g),"nonzero return retains generation");
    check(g.entered==1&&g.completed==1&&g.peak==1,"balanced nonzero accounting");
    /* A destructor reenters twice. A nested zero cannot retire the outer slot. */
    check(nrg_enter(&g)&&nrg_enter(&g),"outer and nested entries");
    unsigned nested=nrg_leave(&g,0);
    check(negative?nested!=0:nested==0,"nested terminal defers retirement");
    check(g.terminal_seen==1&&g.in_flight==1&&!g.unknown,"outer metadata stays available");
    check(nrg_enter(&g)&&!nrg_leave(&g,0),"second destructor callback retains outer slot");
    check(nrg_leave(&g,0),"only final outer completion retires");
    check(g.in_flight==0&&g.entered==g.completed&&g.peak==2&&!g.unknown,"terminal bookkeeping balances");
    check(!nrg_quiet_live(&g),"terminal generation never becomes live again");
    nrg_init(&g);check(nrg_quiet_live(&g)&&g.entered==0,"explicit fresh generation");
    check(!nrg_leave(&g,1)&&g.unknown==2&&g.in_flight==0,"underflow refuses");
    check(!nrg_quiet_live(&g),"underflow is sticky");
    nrg_init(&g);g.entered=0x7ffff000u;
    check(!nrg_enter(&g)&&g.unknown==1&&g.in_flight==0,"event limit refuses without entering");
    nrg_init(&g);
    for(unsigned i=0;i<64;i++)check(nrg_enter(&g),"bounded depth entry");
    check(!nrg_enter(&g)&&g.in_flight==64&&g.unknown==1,"depth overflow refuses");
    for(unsigned i=0;i<64;i++)check(!nrg_leave(&g,1),"nonterminal unwind does not retire");
    check(g.in_flight==0&&g.entered==g.completed&&g.peak==64&&!nrg_quiet_live(&g),"overflow remains unknown after unwind");
    nrg_init(&g);check(nrg_enter(&g)&&nrg_enter(&g),"contradictory return control");
    check(!nrg_leave(&g,0)&&nrg_leave(&g,1)&&g.unknown==4,"nonzero after terminal conservatively flags unknown");
    printf("{\"status\":\"%s\",\"checks\":%u,\"failures\":%u,\"assetsRequired\":false}\n",failures?"FAIL":"PASS",checks,failures);
    return failures?1:0;
}
