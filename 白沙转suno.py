from colorama import init, Fore, Back, Style
分析=0
去咽化=1
去C=1
去闪音=0
改善音节=1

def 声类(index,mode):
    if mode: return ['平','上','去','p入去通谐','t入去通谐','k入去通谐','上去通谐','p入','t入','k入'][index]
    else: return ['','ء','s','бs','ც','ξ','s','б','д','ก'][index]
def 韵尾类(index,mode):
    if mode:return ['','浊唇-软腭:','双唇鼻:','硬腭近:','龈颤:','龈鼻:','软颚鼻:'][index]
    else: return ['','w','m','й','r','n','ง'][index]
def 元音类(index,mode):
    if index==0 : print(Fore.RED + '错误' + Fore.RESET)
    if mode: return ['','开前:','开后:','半闭前:','半闭后:','中央:','闭前:','闭后圆唇:'][index]
    else: return ['','α','ა','ए','o','ă','ი','უ'][index]


def 白沙(text):
    声调,韵尾,元音=0,0,0
    text = text.replace('ᵊ','').replace("ʰ","h")

    if text[-1]=='ʔ':
        text=text[:-1]
        声调=1
    elif text[-1]=='s':
        text=text[:-1]
        if text[-1]=='p':
            text=text[:-1]
            声调=3
        elif text[-1]=='t':
            text=text[:-1]
            声调=4
        elif text[-1]=='k':
            text=text[:-1]
            声调=5
        elif text[-1]=='ʔ':
            text=text[:-1]
            声调=6
        else:
            声调=2
    elif text[-1]=='p':
        text=text[:-1]
        声调=7
    elif text[-1]=='t':
        text=text[:-1]
        声调=8
    elif text[-1]=='k':
        text=text[:-1]
        声调=9

    if text[-1]=='w':
        text=text[:-1]
        韵尾=1
    elif text[-1]=='m':
        text=text[:-1]
        韵尾=2
    elif text[-1]=='j':
        text=text[:-1]
        韵尾=3
    elif text[-1]=='r':
        text=text[:-1]
        韵尾=4
    elif text[-1]=='n':
        text=text[:-1]
        韵尾=5
    elif text[-1]=='ŋ':
        text=text[:-1]
        韵尾=6

    '''if text[-1]=='a':
        text=text[:-1]
        元音=1
    elif text[-1]=='A':
        text=text[:-1]
        元音=2
    elif text[-1]=='e':
        text=text[:-1]
        元音=3
    elif text[-1]=='o':
        text=text[:-1]
        元音=4
    elif text[-1]=='ə':
        text=text[:-1]
        元音=5
    elif text[-1]=='i':
        text=text[:-1]
        元音=6
    elif text[-1]=='u':
        text=text[:-1]
        元音=7'''
    
    if 分析: 
        print(Fore.GREEN + text + Fore.RESET + ' ' + 韵尾类(韵尾,1) + 声类(声调,1),end=' ')
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
        for i in range(len(b)):
            token = b[i]
            # 若被 [] 包裹则不替换，原样保留
            if token.startswith('[') and token.endswith(']'):
                a.append(token)
            else:
                a.append(白沙(token))
        a.append('\n')