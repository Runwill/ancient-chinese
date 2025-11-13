from colorama import init, Fore, Back, Style
分析=0
改善咽化=1
去闪音=0
改善音节=1

def 声类(index,mode):
    if mode: return ['平','上','去','p入去通谐','t入去通谐','k入去通谐','上去通谐','p入','t入','k入','k入/k入去通押'][index]
    else: return ['','ء','s','бs','ც','ξ','s','б','д','ก','h'][index]
def 韵尾类(index,mode):
    if mode:return ['','浊唇-软腭:','双唇鼻:','硬腭近:','龈颤:','龈鼻:','软颚鼻:'][index]
    else: return ['','w','m','й','r','n','ง'][index]
def 元音类(index,mode):
    if index==0 : print(Fore.RED + '错误' + Fore.RESET)
    if mode: return ['','开前:','待定:','半闭前:','半闭后:','中央:','闭前:','闭后圆唇:'][index]
    else: return ['','α','a','ए','o','으','ი','უ'][index]
def 声母类(index,mode):
    if mode: return [
        '','清送气龈有咝塞擦:','清龈有咝塞擦:','浊龈有咝塞擦:','清龈有咝擦-塞:','清龈有咝擦:','清送气龈塞:','清龈塞:','浊龈塞:','清送气双唇塞:','清双唇塞:','浊双唇塞:','清送气软腭塞:','清软腭塞:','浊软腭塞:','清双唇鼻:','浊双唇鼻:','清龈鼻:','浊龈鼻:','清龈颤:','浊龈颤:','超切浊龈颤:','清龈边近:','浊龈边近:','清软腭鼻:','浊软腭鼻:','喉塞','清声门擦','清唇-软腭近','浊唇-软腭近',
        ''
        ][index]
    else: return [
        '','ц','ც','ძ','sд','s','თ','д','д','พ','б','ბ','ข','g','g','mh','m','nh','n','rh','r','r','hl','л','hŋ','ง','ء','ㅎ','wh','و',

        ][index]
def 韵头类(index,mode):
    if mode: return ['','浊龈颤:','咽近-浊龈颤:','咽化浊龈边近:','浊龈边近:','咽化唇-软腭近','浊唇-软腭近', '清硬腭近', '浊硬腭近', '咽近'][index]
    else: return ['','r','عΡ','lع','л','وع','w','hj','й','ع'][index]


def 解析声调(text: str):
    tone_map = {'ps':3, 'ts':4, 'ks':5, 'ʔs':6, 'ʔ':1, 's':2, 'p':7, 't':8, 'k':9, 'h':10}
    for key in sorted(tone_map.keys(), key=lambda k: tone_map[k]):
        if text.endswith(key):
            return text[:-len(key)], tone_map[key]
    return text, 0

def 解析韵尾(text: str):
    coda_map = {'w':1, 'm':2, 'j':3, 'r':4, 'n':5, 'ŋ':6}
    last = text[-1:]
    if last in coda_map:
        return text[:-1], coda_map[last]
    return text, 0

def 解析元音(text: str):
    vowel_map = {'a':1, 'A':2, 'e':3, 'o':4, 'ə':5, 'i':6, 'u':7}
    last = text[-1:]
    if last in vowel_map:
        return text[:-1], vowel_map[last]
    return text, 0

def 解析声母(text: str):
    # 变音处理
    text = text.replace("ʰ","h")
    consonant_map = {'tsh':1, 'ts':2, 'dz':3, 'st':4, 's':5, 'th':6, 't':7, 'd':8, 'ph':9, 'p':10, 'b':11, 'kh':12, 'k':13, 'g':14, 'm̥':15, 'm':16, 'n̥':17, 'n':18, 'r̥':19, 'r':20, 'C.r':21, 'l̥':22, 'l':23, 'ŋ̊':24, 'ŋ':25, 'ʔ':26, 'h':27, 'ẘ':28, 'w':29}
    for cons in sorted(consonant_map.keys(), key=lambda k: consonant_map[k]):
        if text.startswith(cons):
            return text[len(cons):], consonant_map[cons]
    return text, 0

def 解析韵头(text: str):
    consonant_map = {'r':1, 'ˤr':2, 'lˤ':3, 'l':4, 'wˤ':5, 'w':6, 'j̊':7, 'j':8, 'ˤ':9}
    for cons in sorted(consonant_map.keys(), key=lambda k: consonant_map[k]):
        if text.startswith(cons):
            return text[len(cons):], consonant_map[cons]
    return text, 0

def 改善咽化替换(text: str):
    text = text.replace('عΡ','Ρ').replace("ขع","ข").replace('عი','ი')
    return text

def 改善音节替换(text: str):
    text = text
    return text


def 白沙(text):
    声调,韵尾=0,0

    text, 声调 = 解析声调(text)
    text, 韵尾 = 解析韵尾(text)

    if 分析: 
        print(Fore.GREEN + text + Fore.RESET + ' ' + 韵尾类(韵尾,1) + 声类(声调,1),end='')
    else: return 白沙声母韵头(text) + 韵尾类(韵尾,0) + 声类(声调,0)

def NULL(text):
    声调,韵尾,声母,韵头,元音=0,0,0,0,0

    text, 声调 = 解析声调(text)
    text, 韵尾 = 解析韵尾(text)
    text, 声母 = 解析声母(text)
    text, 韵头 = 解析韵头(text)
    text, 元音 = 解析元音(text)
    
    if 分析: 
        print(Fore.RESET + 声母类(声母,1) + 韵头类(韵头,1) + Fore.GREEN + text + Fore.RESET + 韵尾类(韵尾,1) + 声类(声调,1),end='')
    else: 
        value = 声母类(声母,0) + 韵头类(韵头,0) + 解析剩余(text) + 元音类(元音,0) + 韵尾类(韵尾,0) + 声类(声调,0)
        if(改善咽化):
            value = 改善咽化替换(value)
            value = 改善音节替换(value)
        return 合写(value)
    
def 合写(text):
    text = ( text
        .replace("gw","кв") # kw
        .replace("йα","я").replace("йए","е").replace("йუ","ю") # ja ju
        .replace("αw","औ") # aw
    )
    return text

def 解析剩余(text):# 剩下没有移动到null方案里的替换
    if(改善咽化):
        text = text.replace("qhˤe","qhe")
    if(改善音节):
        text = ( text
            .replace("ɢw","gw")
            .replace("mq","q")
            .replace("kph","khw")
            .replace("wr","wˤ")
        )
    text = ( text
        .replace("N","n")
        .replace("tʂ","č")
        .replace("tɕh","ฉ").replace("tɕ","ć").replace("ɕ","ś")
        .replace("dʑ","dź")
        .replace("qh","ყ").replace("qw","къу")
        .replace("ɨ","ừ").replace("ɑ","ا")
        .replace("ɫ","л")
        .replace("ɲ","ñ")
        .replace("ᵯ","m")
        .replace("ʂ","ш")
        .replace("q","ق").replace("ɢ","ق")
        .replace("x","χ")
    )
    return text

def 白沙声母韵头(text):
    text = text.replace("-","").replace("•","").replace('ᵊ','')
    if(改善咽化):
        text = text.replace("khˤ","kh").replace("kˤ","k").replace("gˤ","g").replace("pˤr","pr").replace("qhˤe","qhe").replace("ˤi","i")
    text = text.replace("C","")
    if(去闪音):
        text = text.replace("r","")
    if(改善音节):
        text = ( text
            .replace("ɢw","gw")
            .replace("mq","q")
            .replace("ˤr","ˤ")
            .replace("kph","khw")
            .replace("wr","wˤ")
        )
    text = ( text
        .replace("N","n")
        .replace("tʂ","č")
        .replace("tɕh","ฉ").replace("tɕ","ć").replace("ɕ","ś")
        .replace("tsh","ц").replace("ts","ც")
        .replace("th","თ").replace("t","д")
        .replace("dʑ","dź")
        .replace("dz","ძ")
        .replace("qh","ყ").replace("qw","къу")
        .replace("kh","ข").replace("kw","кв")
        .replace("aw","औ")
        .replace("ja","я").replace("ju","ю")
        .replace("a","α").replace("A","a").replace("e","ए").replace("ə","으").replace("i","ი").replace("u","უ")
        .replace("ɨ","ừ").replace("ɑ","ا")
        .replace("kˤ","კ").replace("k","к")
        .replace("ɫ","л")
        .replace("l̥","л").replace("l","л")
        .replace("ɲ","ñ")
        .replace("ŋ̊","ง").replace("ŋ","ง")
        .replace("ᵯ","m")
        .replace("m̥","m").replace("n̥","n")
        .replace("r̥","Ρ").replace("r","Ρ")
        .replace("ʔ","ء")
        .replace("ʂ","ш")
        .replace("d","द")
        .replace("q","ق").replace("ɢ","ق")
        .replace("b","ბ").replace("p","б")
        .replace("h","ხ")
        .replace("x","χ")
        .replace("ˤ","ع")
    )
    return text


a=[]
while(1):
    b=list(map(str,input().split()))
    if(b==['1']):
        for i in a:
            print(Fore.CYAN + str(i) + Fore.RESET, end='')
            if i!= '\n':
                print(' ', end='')
        a=[]
        print('')
    else:
        if 分析:
            for token in b:
                if token.startswith('[') and token.endswith(']'):
                    print(token, end=' ')
                else:
                    NULL(token)
                    print(' ', end='')
            print()
        else:
            for token in b:
                if token.startswith('[') and token.endswith(']'):
                    a.append(token)
                else:
                    a.append(NULL(token))
            a.append('\n')