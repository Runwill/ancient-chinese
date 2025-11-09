from colorama import init, Fore, Back, Style
分析=1
去咽化=1
去C=1
去闪音=0
改善音节=1

def 声类(index,mode):
    if mode: return ['平','上','去','p入去通谐','t入去通谐','k入去通谐','上去通谐','p入','t入','k入','k入/k入去通押'][index]
    else: return ['','ء','s','бs','ც','ξ','s','б','д','ก','ხ'][index]
def 韵尾类(index,mode):
    if mode:return ['','浊唇-软腭:','双唇鼻:','硬腭近:','龈颤:','龈鼻:','软颚鼻:'][index]
    else: return ['','w','m','й','r','n','ง'][index]
def 元音类(index,mode):
    if index==0 : print(Fore.RED + '错误' + Fore.RESET)
    if mode: return ['','开前:','待定:','半闭前:','半闭后:','中央:','闭前:','闭后圆唇:'][index]
    else: return ['','α','a','ए','o','으','ი','უ'][index]
def 声母类(index,mode):
    if mode: return ['','开前:','待定:','半闭前:','半闭后:','中央:','闭前:','闭后圆唇:'][index]
    else: return ['','α','a','ए','o','으','ი','უ'][index]


def 解析声调(text: str):
    tone_map = {'ps':3, 'ts':4, 'ks':5, 'ʔs':6, 'ʔ':1, 's':2, 'p':7, 't':8, 'k':9, 'h':10}
    for key in sorted(tone_map.keys(), key=lambda k: tone_map[k]):
        if text.startswith(key):
            return text[len(key):], tone_map[key]
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
    consonant_map = {'tsʰ':1, 'ts':2}
    for cons in sorted(consonant_map.keys(), key=lambda k: consonant_map[k]):
        if text.startswith(cons):
            return text[len(cons):], consonant_map[cons]
    return text, 0


def 白沙(text):
    声调,韵尾=0,0
    # 变音处理
    text = text.replace('ᵊ','').replace("ʰ","h")

    # 解析
    text, 声调 = 解析声调(text)
    text, 韵尾 = 解析韵尾(text)
    
    if 分析: 
        print(Fore.GREEN + text + Fore.RESET + ' ' + 韵尾类(韵尾,1) + 声类(声调,1),end='')
    else: return 白沙声母韵头(text) + 韵尾类(韵尾,0) + 声类(声调,0)

def NULL(text):
    声调,韵尾,声母,元音=0,0,0,0

    # 解析
    text, 声调 = 解析声调(text)
    text, 韵尾 = 解析韵尾(text)
    text, 声母 = 解析声母(text)
    text, 元音 = 解析元音(text)
    
    if 分析: 
        print(Fore.GREEN + text + Fore.RESET + ' ' + 元音类(元音,1) + 韵尾类(韵尾,1) + 声类(声调,1),end='')
    else: return 白沙声母韵头(text) + 韵尾类(韵尾,0) + 声类(声调,0)

def 白沙声母韵头(text):
    text = text.replace("-","").replace("•","")
    if(去咽化):
        text = text.replace("khˤ","kh").replace("kˤ","k").replace("gˤ","g").replace("pˤr","pr").replace("qhˤe","qhe").replace("ˤi","i")
    if(去C):
        text = text.replace("C","")
    else:
        text = text.replace("C","კ")
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
        #.replace("w","و")
        #晚期上古
        .replace("j","й")
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
                白沙(token)
                print(' ', end='')
            print()
        else:
            for token in b:
                a.append(白沙(token))
            a.append('\n')