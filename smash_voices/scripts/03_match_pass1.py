import json,re,difflib
names=["マリオ|mario","ネス|ness","キャプテン・ファルコン|captain falcon|captain vulture","プリン|jigglypuff","ドンキーコング|donkey kong","リンク|link","サムス|samus","ヨッシー|yoshi","カービィ|kirby","フォックス|fox",
"ピカチュウ|pikachu","ルイージ|luigi","ピーチ|peach","クッパ|bowser","アイスクライマー|ice climbers|ice climber|ice limer","シーク|sheik","ゼルダ|zelda","ドクターマリオ|dr. mario|doctor mario","ピチュー|pichu","ファルコ|falco",
"マルス|marth","こどもリンク|young link","ガノンドロフ|ganondorf","ミュウツー|mewtwo","ロイ|roy","ゲーム&ウォッチ|mr. game & watch|game and watch","メタナイト|meta knight","ピット|pit","ゼロスーツサムス|zero suit samus","ワリオ|wario",
"スネーク|snake","アイク|ike","ポケモントレーナー|pokemon trainer","ディディーコング|diddy kong","リュカ|lucas","ソニック|sonic","デデデ|dedede|king dedede","ピクミン&オリマー|olimar|pikmin","ルカリオ|lucario","ロボット|robot|r.o.b",
"トゥーンリンク|toon link","ウルフ|wolf","ルキナ|lucina","ブラックピット|dark pit","むらびと|villager","ロックマン|mega man","WiiFitトレーナー|wii fit trainer","ロゼッタ&チコ|rosalina|rosanna","リトル・マック|little mac","ゲッコウガ|greninja",
"Miiファイター(格闘)|mii brawler","Miiファイター(剣術)|mii swordfighter","Miiファイター(射撃)|mii gunner","パルテナ|palutena","パックマン|pac-man|pacman","ルフレ|robin","シュルク|shulk","クッパJr.|bowser jr","ダックハント|duck hunt","リュウ|ryu",
"クラウド|cloud","カムイ|corrin","ベヨネッタ|bayonetta","パックンフラワー|piranha plant","デイジー|daisy","クロム|chrom","ダークサムス|dark samus","ケン|ken","インクリング|inkling","リドリー|ridley",
"シモン|simon","リヒター|richter","キングクルール|king k. rool|k. rool","しずえ|isabelle","ガオガエン|incineroar","勇者(ドラクエ)|hero","ジョーカー|joker","バンカズ|banjo","テリー|terry","ベレト＆ベレス|byleth",
"ミェンミェン|min min","スティーブ|steve|alex","セフィロス|sephiroth","ホムラ＆ヒカリ|pyra|mythra","カズヤ|kazuya","ソラ|sora"]
assert len(names)==86
norm=lambda s:re.sub(r"[^a-z]","",s.lower())
segs=[json.loads(l) for l in open("work/pass1_prompted.jsonl")][:115]
res={}
for n,e in enumerate(names,1):
    al=e.split("|")[1:]; best=(0,None)
    for s in segs:
        t=norm(s["text"])
        for a in al:
            a=norm(a)
            r=1.0 if (a in t and len(t)<=len(a)+4) else difflib.SequenceMatcher(None,a,t).ratio()
            if r>best[0]: best=(r,s["i"])
    res[n]=best
    s=segs[best[1]] if best[1] is not None else {}
    print(n,e.split("|")[0],round(best[0],2),best[1],round(s.get("start",0),1),s.get("text"))
