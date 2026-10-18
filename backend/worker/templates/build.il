;; ============================================================
;; P2 BUILD v3 — attempt #3, new isolated workspace
;; @LIB@.
;; Fixes vs v2 (per build_rc_lpf2.log evidence, exactly 3):
;;   F7 near undefined in ocean replay -> custom bNear (tol 1e-6)
;;   F8 gnd wire label split symbol-derived net gnd! (schCheck
;;      reported 4x "Net gnd shorted to net gnd!") -> drop the
;;      gnd label; net keeps symbol-derived name gnd!
;;   F9 mexp was a flat list passed to assoc -> proper alist
;; Gate policy unchanged: any ASSERT_FAIL -> evidence dbSave -> stop.
;; ============================================================
printf("BUILD_START\n")
LIB="@LIB@"
CELL="rc_lpf"
DBPATH="@DBPATH@"
FAILS=0

procedure( bChk(ok msg)
  if( ok then printf("ASSERT_PASS %s\n" msg)
      else printf("ASSERT_FAIL %s\n" msg) FAILS=FAILS+1 )
)
procedure( bNear(a b) abs(a-b)<=1e-6 )
procedure( bPinPos(mcv termName)
  let( (term pin fg bb)
    term = car(setof(tt mcv~>terminals equal(tt~>name termName)))
    pin  = (term && car(term~>pins))
    fg   = (pin && pin~>fig)
    bb   = (fg && fg~>bBox)
    if( bb then
      list( (xCoord(car(bb))+xCoord(cadr(bb)))/2.0
            (yCoord(car(bb))+yCoord(cadr(bb)))/2.0 )
    else nil )
  )
)
procedure( bXform(pt orient)
  cond(
    ( equal(orient "R90") list(-cadr(pt) car(pt)) )
    ( equal(orient "R0")  pt )
    ( t nil )
  )
)
procedure( bPinAbs(mcv termName ox oy orient)
  let( (pp px)
    pp = bPinPos(mcv termName)
    px = (pp && bXform(pp orient))
    if( px then list(ox+car(px) oy+cadr(px)) else nil )
  )
)
procedure( bInRange(p bb)
  p && bb && car(bb) && cadr(bb) &&
  car(p)>=xCoord(car(bb))-0.01 && car(p)<=xCoord(cadr(bb))+0.01 &&
  cadr(p)>=yCoord(car(bb))-0.01 && cadr(p)<=yCoord(cadr(bb))+0.01
)
procedure( bProp(inst pname pval)
  let( (cur)
    errset(dbReplaceProp(inst pname "string" pval) t)
    cur = dbGet(inst pname)
    unless( equal(cur pval)
      errset(dbCreateProp(inst pname "string" pval) t)
      cur = dbGet(inst pname)
    )
    printf("PARAM_SET inst=%s %s=%L readback=%L\n" inst~>name pname pval cur)
    equal(cur pval)
  )
)
procedure( bCdfInfo(inst)
  let( (r)
    r = errset(cdfGetInstCDF(inst) t)
    if( r && car(r) then
      foreach( p car(r)~>parameters
        printf("CDF_PARAM %s name=%L type=%L\n" inst~>name p~>name p~>type) )
      t
    else
      printf("CDF_INFO_UNAVAILABLE inst=%s\n" inst~>name) nil )
  )
)

;; ---------- library ----------
libObj = ddGetObj(LIB)
unless( libObj
  r = errset(ddCreateLib(LIB DBPATH) t)
  printf("DD_CREATE_LIB=%L\n" r)
)
libObj = ddGetObj(LIB)
bChk( libObj sprintf(nil "ddGetObj(%s) non-nil" LIB) )
when( libObj
  rp = ddGetObjReadPath(libObj)
  bChk( equal(rp DBPATH) sprintf(nil "lib readpath=%L expected=%L" rp DBPATH) )
)

;; ---------- masters (read-only) ----------
mvV = dbOpenCellViewByType("analogLib" "vpulse" "symbol" "schematicSymbol" "r")
mvR = dbOpenCellViewByType("analogLib" "res"   "symbol" "schematicSymbol" "r")
mvC = dbOpenCellViewByType("analogLib" "cap"   "symbol" "schematicSymbol" "r")
mvG = dbOpenCellViewByType("analogLib" "gnd"   "symbol" "schematicSymbol" "r")
bChk(mvV "master analogLib/vpulse/symbol open r")
bChk(mvR "master analogLib/res/symbol open r")
bChk(mvC "master analogLib/cap/symbol open r")
bChk(mvG "master analogLib/gnd/symbol open r")

;; ---------- master geometry sanity (matches preflight) ----------
ppV1 = bPinPos(mvV "PLUS")  ppV0 = bPinPos(mvV "MINUS")
bChk( ppV1 && ppV0 && bNear(car(ppV1) 0.0) && bNear(cadr(ppV1) 0.0)
      sprintf(nil "vpulse PLUS at origin: %L" ppV1) )
bChk( ppV0 && bNear(car(ppV0) 0.0) && bNear(cadr(ppV0) -0.375)
      sprintf(nil "vpulse MINUS at (0,-0.375): %L" ppV0) )
ppR1 = bPinPos(mvR "PLUS")  ppR0 = bPinPos(mvR "MINUS")
bChk( ppR1 && bNear(car(ppR1) 0.0) && bNear(cadr(ppR1) 0.0)
      sprintf(nil "res PLUS at origin: %L" ppR1) )
bChk( ppR0 && bNear(cadr(ppR0) -0.375) sprintf(nil "res MINUS at (0,-0.375): %L" ppR0) )
ppC1 = bPinPos(mvC "PLUS")  ppC0 = bPinPos(mvC "MINUS")
bChk( ppC1 && bNear(car(ppC1) 0.0) && bNear(cadr(ppC1) 0.0)
      sprintf(nil "cap PLUS at origin: %L" ppC1) )
bChk( ppC0 && bNear(cadr(ppC0) -0.375) sprintf(nil "cap MINUS at (0,-0.375): %L" ppC0) )
gterms = (mvG && mvG~>terminals~>name)
bChk( gterms && length(gterms)==1 sprintf(nil "gnd single terminal actual=%L" gterms) )
GT = car(gterms)
gp = bPinPos(mvG GT)
bChk( gp && bNear(car(gp) 0.0) && bNear(cadr(gp) 0.0)
      sprintf(nil "gnd pin at origin term=%L pos=%L" GT gp) )

if( FAILS>0 then
  printf("BUILD_ABORTED_PRE_CREATE FAILS=%L\n" FAILS)
  error("BUILD_FAILED")
)

;; ---------- cellview (create) ----------
when(ddGetObj(LIB CELL "schematic") error("REFUSE_EXISTING_CELL"))
cv = dbOpenCellViewByType(LIB CELL "schematic" "schematic" "a")
bChk(cv "open/create rc_lpf/schematic mode a")
bChk( cv && equal(cv~>mode "a") sprintf(nil "cv mode=%L" (cv && cv~>mode)) )

;; ---------- instances (R90 for V1/R1/C1, R0 for GND0) ----------
IV = schCreateInst(cv mvV "V1"   list(0.0 0.0) "R90")
IR = schCreateInst(cv mvR "R1"   list(3.0 0.0) "R90")
IC = schCreateInst(cv mvC "C1"   list(6.0 0.0) "R90")
IG = schCreateInst(cv mvG "GND0" list(3.0 -1.0) "R0")
foreach( i list(IV IR IC IG)
  when( i printf("POSTCREATE %s origin=%L orient=%L instTerms=%L bBox=%L\n"
                 i~>name i~>origin i~>orient length(i~>instTerms) i~>bBox) )
)
bChk( IV && IR && IC && IG "all 4 instances created via schCreateInst" )
if( !(IV && IR && IC && IG) then
  dbSave(cv)
  printf("BUILD_FAILED_INSTS\n")
  error("BUILD_FAILED")
)

;; ---------- CDF params ----------
bCdfInfo(IV)
bChk( bProp(IR "r" "@R@") "parameter r persisted" )
bChk( bProp(IC "c" "@C@") "parameter c persisted" )
bChk( bProp(IV "v1" "@LOW@") "parameter v1 persisted" )
bChk( bProp(IV "v2" "@HIGH@") "parameter v2 persisted" )
bChk( bProp(IV "per" "@PERIOD@") "parameter per persisted" )
bChk( bProp(IV "pw" "@WIDTH@") "parameter pw persisted" )
bChk( bProp(IV "tr" "@RISE@") "parameter tr persisted" )
bChk( bProp(IV "tf" "@FALL@") "parameter tf persisted" )
bChk( bProp(IV "acm" "@ACMAG@") "parameter acm persisted" )

bChk( bProp(IV "td" "@DELAY@") "delay persisted" )

;; ---------- wire geometry (computed from placement constants) ----------
V1P = bPinAbs(mvV "PLUS"  0.0 0.0  "R90")
V1M = bPinAbs(mvV "MINUS" 0.0 0.0  "R90")
R1P = bPinAbs(mvR "PLUS"  3.0 0.0  "R90")
R1M = bPinAbs(mvR "MINUS" 3.0 0.0  "R90")
C1P = bPinAbs(mvC "PLUS"  6.0 0.0  "R90")
C1M = bPinAbs(mvC "MINUS" 6.0 0.0  "R90")
G0T = bPinAbs(mvG GT      3.0 -1.0 "R0")
printf("PINS_ABS V1P=%L V1M=%L R1P=%L R1M=%L C1P=%L C1M=%L G0T=%L\n"
       V1P V1M R1P R1M C1P C1M G0T)
bChk( V1P && V1M && R1P && R1M && C1P && C1M && G0T
      "all absolute pin positions resolved" )
;; F5: placement verified against persisted instance bBox containment
bChk( IV && bInRange(V1P IV~>bBox) && bInRange(V1M IV~>bBox)
      sprintf(nil "V1 pins within bBox=%L" (IV && IV~>bBox)) )
bChk( IR && bInRange(R1P IR~>bBox) && bInRange(R1M IR~>bBox)
      sprintf(nil "R1 pins within bBox=%L" (IR && IR~>bBox)) )
bChk( IC && bInRange(C1P IC~>bBox) && bInRange(C1M IC~>bBox)
      sprintf(nil "C1 pins within bBox=%L" (IC && IC~>bBox)) )
bChk( IG && bInRange(G0T IG~>bBox)
      sprintf(nil "GND0 pin within bBox=%L" (IG && IG~>bBox)) )
;; R90 layout invariants: MINUS exactly 0.375 right of PLUS, same y
bChk( V1P && V1M && bNear(car(V1M)-car(V1P) 0.375) && bNear(cadr(V1M) cadr(V1P))
      sprintf(nil "V1 MINUS right of PLUS by 0.375: %L %L" V1P V1M) )
bChk( R1P && R1M && bNear(car(R1M)-car(R1P) 0.375) && bNear(cadr(R1M) cadr(R1P))
      sprintf(nil "R1 MINUS right of PLUS by 0.375: %L %L" R1P R1M) )
bChk( C1P && C1M && bNear(car(C1M)-car(C1P) 0.375) && bNear(cadr(C1M) cadr(C1P))
      sprintf(nil "C1 MINUS right of PLUS by 0.375: %L %L" C1P C1M) )
bChk( G0T && bNear(car(G0T) 3.0) && bNear(cadr(G0T) -1.0)
      sprintf(nil "GND0 pin at junction (3,-1): %L" G0T) )

YT = max(cadr(V1P) cadr(R1P)) + 0.625
YG = -1.0
;; vin: V1:PLUS up and over to R1:PLUS (avoids V1:MINUS pin on straight path)
wVinR = errset(schCreateWire(cv "draw" "orthogonal"
  list( V1P list(car(V1P) YT) list(car(R1P) YT) R1P ) 0.0625 0.0625 0.0) t)
bChk( wVinR && car(wVinR) sprintf(nil "wire vin created raw=%L" wVinR) )
;; out: R1:MINUS straight to C1:PLUS (no pin lies between)
wOutR = errset(schCreateWire(cv "draw" "orthogonal"
  list( R1M C1P ) 0.0625 0.0625 0.0) t)
bChk( wOutR && car(wOutR) sprintf(nil "wire out created raw=%L" wOutR) )
;; gnd rail split at GND0 pin junction (3,-1): W1 left, W2 right
wG1R = errset(schCreateWire(cv "draw" "orthogonal"
  list( V1M list(car(V1M) YG) list(3.0 YG) ) 0.0625 0.0625 0.0) t)
bChk( wG1R && car(wG1R) sprintf(nil "wire gnd-left created raw=%L" wG1R) )
wG2R = errset(schCreateWire(cv "draw" "orthogonal"
  list( list(3.0 YG) list(car(C1M) YG) C1M ) 0.0625 0.0625 0.0) t)
bChk( wG2R && car(wG2R) sprintf(nil "wire gnd-right created raw=%L" wG2R) )

;; ---------- net labels (name the nets) ----------
;; F8: no label on the gnd rail — the net name comes from the
;; gnd symbol terminal (gnd!); a wire label "gnd" split the net.
procedure( bGlue(wr)
  let( (x) x = car(wr) if(listp(x) car(x) x) )
)
labVinR = errset(schCreateWireLabel(cv bGlue(wVinR)
  list((car(V1P)+car(R1P))/2.0 YT) "vin" "lowerCenter" "R0" "stick" 0.0625 nil) t)
bChk( labVinR && car(labVinR) sprintf(nil "label vin raw=%L" labVinR) )
labOutR = errset(schCreateWireLabel(cv bGlue(wOutR)
  list((car(R1M)+car(C1P))/2.0 cadr(R1M)) "out" "lowerCenter" "R0" "stick" 0.0625 nil) t)
bChk( labOutR && car(labOutR) sprintf(nil "label out raw=%L" labOutR) )

;; ---------- connectivity extraction ----------
chkR = errset(schCheck(cv) t)
printf("SCHCHECK_RAW=%L\n" chkR)
bChk(equal(chkR list(list(0 0))) "schematic check zero errors and warnings")

;; ---------- authoritative in-session assertions ----------
ACT = nil
foreach( i cv~>instances
  foreach( it i~>instTerms
    nn = (it~>net && it~>net~>name)
    ACT = cons(list(strcat(i~>name "/" it~>term~>name)
                        if(nn nn "NIL_NET")) ACT)
  )
)
GTsym = strcat("GND0/" GT)
EXP = list(
  list("V1/PLUS" "vin") list("R1/PLUS" "vin")
  list("R1/MINUS" "out") list("C1/PLUS" "out")
  list("V1/MINUS" "gnd!") list("C1/MINUS" "gnd!")
  list(GTsym "gnd!") )
foreach( e EXP
  ent = assoc(car(e) ACT)
  bChk( ent && equal(cadr(ent) cadr(e))
        sprintf(nil "assoc %s expected->%s actual=%L"
                car(e) cadr(e) (ent && cadr(ent))) )
)
bChk( length(ACT)==7 sprintf(nil "total instTerms==7 actual=%L" length(ACT)) )
;; F9: mexp is a proper alist
mexp = list( list("V1" "vpulse") list("R1" "res")
             list("C1" "cap")   list("GND0" "gnd") )
foreach( pn list("V1" "R1" "C1" "GND0")
  ii = car(setof(x cv~>instances equal(x~>name pn)))
  bChk( ii sprintf(nil "instance %s present" pn) )
  when( ii
    mcell = (ii~>master && ii~>master~>cellName)
    bChk( mcell && equal(mcell cadr(assoc(pn mexp)))
          sprintf(nil "%s master cell=%L" pn mcell) )
  )
)
bChk( IV && length(IV~>instTerms)==2 sprintf(nil "V1 instTerms==2 actual=%L" (IV && length(IV~>instTerms))) )
bChk( IR && length(IR~>instTerms)==2 sprintf(nil "R1 instTerms==2 actual=%L" (IR && length(IR~>instTerms))) )
bChk( IC && length(IC~>instTerms)==2 sprintf(nil "C1 instTerms==2 actual=%L" (IC && length(IC~>instTerms))) )
bChk( IG && length(IG~>instTerms)==1 sprintf(nil "GND0 instTerms==1 actual=%L" (IG && length(IG~>instTerms))) )
nnames = cv~>nets~>name
bChk( length(cv~>nets)==3 sprintf(nil "nets==3 actual=%L" nnames) )
foreach( wn list("vin" "out" "gnd!")
  bChk( member(wn nnames) sprintf(nil "net %s named" wn) )
)
foreach( n cv~>nets
  printf("NET_POST %s instTerms=%L figs=%L\n" n~>name length(n~>instTerms) length(n~>figs))
  bChk( length(n~>figs)>=1 sprintf(nil "net %s figs>=1 actual=%L" n~>name length(n~>figs)) )
)
printf("SHAPES_TOTAL=%L\n" length(cv~>shapes))

;; ---------- finish ----------
if( FAILS>0 then
  dbSave(cv)
  printf("BUILD_FAILED FAILS=%L (evidence saved to new lib only)\n" FAILS)
  error("BUILD_FAILED")
else
  printf("DBSAVE=%L\n" dbSave(cv))
  dbClose(cv)
  printf("BUILD_PASSED\n")
)
exit()
