;; ============================================================
;; P3 POST-SAVE PROBE v3: fresh READ-ONLY ocean session,
;; workspace @LIB@.
;; Carried fixes: connectivity reads use documented attribute
;; instTerms. New vs v2 (same evidence as build v3):
;;   F8 gnd net name is the symbol-derived "gnd!" (no label)
;;   F9 mexp is a proper alist
;; Verifies persisted masters, instTerms, terminal-to-net assoc,
;; net names, and instance params. No write APIs. No dbSave.
;; ============================================================
printf("PROBE_START\n")
LIB="@LIB@"
CELL="rc_lpf"
FAILS=0
procedure( pChk(ok msg)
  if( ok then printf("PROBE_PASS %s\n" msg)
      else printf("PROBE_FAIL %s\n" msg) FAILS=FAILS+1 )
)

cv = car(errset(dbOpenCellViewByType(LIB CELL "schematic" "schematic" "r") t))
pChk(cv "post-save open mode r")
pChk( cv && equal(cv~>mode "r") sprintf(nil "mode=%L" (cv && cv~>mode)) )
when( cv
  printf("PROBE_CONNECTIVITY_LAST_UPDATED=%L\n" cv~>connectivityLastUpdated)
  insts = cv~>instances
  pChk( length(insts)==4 sprintf(nil "instances==4 actual=%L" insts~>name) )
  ACT = nil
  foreach( i insts
    printf("PROBE_INST %s master=%L origin=%L instTerms=%L\n"
           i~>name i~>master i~>origin length(i~>instTerms))
    pChk( i~>master sprintf(nil "%s master non-nil" i~>name) )
    when( i~>master
      pChk( equal(i~>master~>libName "analogLib")
            sprintf(nil "%s master lib=%L" i~>name i~>master~>libName) )
      pChk( equal(i~>master~>viewName "symbol")
            sprintf(nil "%s master view=%L" i~>name i~>master~>viewName) )
    )
    foreach( it i~>instTerms
      nn = (it~>net && it~>net~>name)
      printf("PROBE_INSTTERM inst=%s term=%s net=%L\n"
             i~>name it~>term~>name (nn || "NIL_NET"))
      ACT = cons(list(strcat(i~>name "/" it~>term~>name)
                          if(nn nn "NIL_NET")) ACT)
    )
  )
  mexp = list( list("V1" "vpulse") list("R1" "res")
               list("C1" "cap")   list("GND0" "gnd") )
  foreach( pn list("V1" "R1" "C1" "GND0")
    ii = car(setof(x insts equal(x~>name pn)))
    pChk( ii sprintf(nil "%s present" pn) )
    when( ii
      pChk( ii~>master && equal(ii~>master~>cellName cadr(assoc(pn mexp)))
            sprintf(nil "%s master cell=%L expected=%L"
                    pn (ii~>master && ii~>master~>cellName) cadr(assoc(pn mexp))) )
    )
  )
  IV = car(setof(x insts equal(x~>name "V1")))
  IR = car(setof(x insts equal(x~>name "R1")))
  IC = car(setof(x insts equal(x~>name "C1")))
  IG = car(setof(x insts equal(x~>name "GND0")))
  pChk( IV && length(IV~>instTerms)==2 sprintf(nil "V1 instTerms==2 actual=%L" (IV && length(IV~>instTerms))) )
  pChk( IR && length(IR~>instTerms)==2 sprintf(nil "R1 instTerms==2 actual=%L" (IR && length(IR~>instTerms))) )
  pChk( IC && length(IC~>instTerms)==2 sprintf(nil "C1 instTerms==2 actual=%L" (IC && length(IC~>instTerms))) )
  pChk( IG && length(IG~>instTerms)==1 sprintf(nil "GND0 instTerms==1 actual=%L" (IG && length(IG~>instTerms))) )
  ;; expected terminal-to-net associations
  gt = nil
  when( IG && length(IG~>instTerms)==1
    gt = car(IG~>instTerms)~>term~>name )
  EXP = list(
    list("V1/PLUS" "vin") list("R1/PLUS" "vin")
    list("R1/MINUS" "out") list("C1/PLUS" "out")
    list("V1/MINUS" "gnd!") list("C1/MINUS" "gnd!") )
  when( gt EXP = cons(list(strcat("GND0/" gt) "gnd!") EXP) )
  foreach( e EXP
    ent = assoc(car(e) ACT)
    pChk( ent && equal(cadr(ent) cadr(e))
          sprintf(nil "assoc %s expected->%s actual=%L"
                  car(e) cadr(e) (ent && cadr(ent))) )
  )
  pChk( gt sprintf(nil "GND0 terminal name known (%L)" gt) )
  pChk( length(ACT)==7 sprintf(nil "total instTerms==7 actual=%L" length(ACT)) )
  ;; nets: names + wire figure geometry (reported separately from instTerms)
  nnames = cv~>nets~>name
  pChk( length(cv~>nets)==3 sprintf(nil "nets==3 actual=%L" nnames) )
  foreach( wn list("vin" "out" "gnd!")
    pChk( member(wn nnames) sprintf(nil "net %s named" wn) )
  )
  foreach( n cv~>nets
    printf("PROBE_NET %s instTerms=%L figs=%L\n"
           n~>name length(n~>instTerms) length(n~>figs))
    pChk( length(n~>figs)>=1 sprintf(nil "net %s figs>=1" n~>name) )
  )
  printf("PROBE_SHAPES_TOTAL=%L\n" length(cv~>shapes))
  pChk(IV && equal(IV~>td "@DELAY@") "delay persisted")
  ;; persisted instance params
  pChk( IV && equal(IV~>v1 "@LOW@")     sprintf(nil "V1.v1 persisted =%L" (IV && IV~>v1)) )
  pChk( IR && equal(IR~>r "@R@")     sprintf(nil "R1.r persisted =%L" (IR && IR~>r)) )
  pChk( IC && equal(IC~>c "@C@")   sprintf(nil "C1.c persisted =%L" (IC && IC~>c)) )
  pChk( IV && equal(IV~>v2 "@HIGH@")     sprintf(nil "V1.v2 persisted =%L" (IV && IV~>v2)) )
  pChk( IV && equal(IV~>acm "@ACMAG@")    sprintf(nil "V1.acm persisted =%L" (IV && IV~>acm)) )
  pChk( IV && equal(IV~>per "@PERIOD@") sprintf(nil "V1.per persisted =%L" (IV && IV~>per)) )
  pChk( IV && equal(IV~>pw "@WIDTH@") sprintf(nil "V1.pw persisted =%L" (IV && IV~>pw)) )
  pChk( IV && equal(IV~>tr "@RISE@") "V1.tr persisted =1n" )
  pChk( IV && equal(IV~>tf "@FALL@") "V1.tf persisted =1n" )
)
if( FAILS>0 then
  printf("PROBE_RESULT=FAIL FAILS=%L\n" FAILS)
  error("PROBE_FAILED")
else
  printf("PROBE_RESULT=PASS\n")
)
exit()
