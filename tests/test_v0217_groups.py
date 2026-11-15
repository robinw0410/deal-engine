"""v0.2.17, part A: a group named by the LLM classification is implausible when that group's exclude (or,
as before, its veto) hits the title, unless the exclude only passes the title on to a later group (the
fall-through the model may overrule). Groups: a copy of the real market groups of a deal-watch search
(name, match, exclude, veto, min, max, in config order)."""

from deal_engine.core import history
from deal_engine.core.groups import classified_market_group, from_classification, match_group
from deal_engine.core.market import classified_sample

# fmt: off
REAL = [
    {
        'name': 'Xbox Controller',
        'match': 'xbox.*\\b(controller\\w*|gamepads?)\\b|\\b(controller\\w*|gamepads?)\\b.*xbox',
        'exclude': '^\\W*(?:(?:verkaufe\\w*|biete|tausche|suche|neu\\w*|top|original\\w*|mein\\w{0,2})\\W+)*(sony\\s+|microsoft\\s+)?(ps\\s?[45]|playstation\\s*[45]|xbox\\s+(series\\s+[xs]|one(\\s+[xs])?))(\\s+(pro|slim|digital|disc))*\\s*(\\+|\\bmit\\b|\\binkl\\b|\\binklusive\\b|\\bsamt\\b|\\bplus\\b|\\bund\\b|&)|^\\W*(?:(?:verkaufe\\w*|biete|tausche|suche|neu\\w*|top|original\\w*|mein\\w{0,2})\\W+)*(sony\\s+)?(ps\\s?[45]|playstation\\s*[45])(\\s+(pro|slim|digital|disc))+\\W*\\d+\\s*(x\\s*)?(controller\\w*|gamepads?|pads?|joypads?)\\b|\\bohne\\s+(\\w+\\s+)?(controller|gamepad|pad)|elite|powera|power a|8bitdo|nacon|hori\\b|turtle beach|razer|gulikit|ipega|gamesir|bigben|snakebyte|thrustmaster|pdp\\b|afterglow|rock candy|easysmx|kompatibel|compatible|nachbau|replica|klon|clone|drittanbieter|third.?party|no.?name|china|generic|ähnlich|aehnlich|fake|nicht original|kein original|^\\W*(?:(?:verkaufe\\w*|biete|tausche|suche|neu\\w*|top|original\\w*|mein\\w{0,2})\\W+)*(sony\\s+|microsoft\\s+|nintendo\\s+)?(ps[45]|playstation\\s*[45]|xbox\\s+(series\\s+[xs]|one(\\s+[xs])?)|switch)\\b[^+]*?(\\+|\\bmit\\b|\\binkl\\.?|\\bund\\b|&)\\s*(\\d+\\s*)?(x\\s*)?(original\\s+)?(dualsense|dualshock|controller|pro\\s*controller|joy[- ]?cons?)|konsole|console|\\bdisc\\b|digital edition|\\b\\d+\\s?(tb|gb)\\b|^\\W*(?:(?:verkaufe\\w*|biete|tausche|suche|neu\\w*|top|original\\w*|mein\\w{0,2})\\W+)*(sony\\s+|microsoft\\s+)?(ps\\s?[45]|playstation\\s*[45]|xbox\\s+(series\\s+[xs]|one(\\s+[xs])?))(\\s+(pro|slim|digital|disc|edition|\\d+\\s*[gt]b))*\\W+(controller\\w*\\s+(fehl\\w*|nicht\\s+dabei)|keine?n?\\s+controller\\w*)\\W*$|^\\W*(?:(?:verkaufe\\w*|biete|tausche|suche|neu\\w*|top|original\\w*|mein\\w{0,2})\\W+)*(microsoft\\s+)?xbox\\s+(series\\s+[xs]|one(\\s+[xs])?)\\b[\\w\\s]*?\\b\\d+\\s*(x\\s*)?(spiel(e|en)?|games?)\\b.*\\b\\d+\\s*(x\\s*)?(controller\\w*|gamepads?)\\b|x[- ]?box[- ]?\\s*360|\\bx\\s?360\\b|\\b360\\b(?!\\s*(?:°|grad|degree|mah))|scuf|aim\\s*controllers?|aimcontrollers?',
        'min': 15,
        'max': 80,
    },
    {
        'name': 'Joy-Con einzeln',
        'match': 'joy[- ]?con.*(?:\\b(?:links|linke[rnms]?|left|sx|sinistr[oa]|links(?:hand|seitig\\w*)|hac[- ]?015|rechts|rechte[rnms]?|right|dx|destr[oa]|rechts(?:hand|seitig\\w*)|hac[- ]?016|[lr]|einzel\\w*|single)\\b|\\b1\\s*(?:stück|stk)\\b)|\\b(?:links|linke[rnms]?|left|sx|sinistr[oa]|links(?:hand|seitig\\w*)|hac[- ]?015|rechts|rechte[rnms]?|right|dx|destr[oa]|rechts(?:hand|seitig\\w*)|hac[- ]?016|[lr]|einzel\\w*|single)\\b.*joy[- ]?con',
        'exclude': '^(?:(?!\\b(?:auch|also)\\b).)*?\\bswitch\\s*2\\b|joy[- ]?cons?\\s*2\\b(?!\\s*(?:x|stk|stück))|paar|\\bset\\b|\\b(?:links|linke[rnms]?|left|sx|sinistr[oa]|links(?:hand|seitig\\w*)|hac[- ]?015)\\b.*\\b(?:rechts|rechte[rnms]?|right|dx|destr[oa]|rechts(?:hand|seitig\\w*)|hac[- ]?016)\\b|\\b(?:rechts|rechte[rnms]?|right|dx|destr[oa]|rechts(?:hand|seitig\\w*)|hac[- ]?016)\\b.*\\b(?:links|linke[rnms]?|left|sx|sinistr[oa]|links(?:hand|seitig\\w*)|hac[- ]?015)\\b|\\bl\\)?\\s*(?:\\+|&|/|und|and)\\s*\\(?r\\b|\\br\\)?\\s*(?:\\+|&|/|und|and)\\s*\\(?l\\b|joy[- ]?cons\\b.*\\b(?:linke[rn]?|rechte[rn]?)\\b|pair|\\bboth\\b|\\b2er\\b|beide|\\b2\\s*(x|stk|stück)|konsole|console|ohne\\s*joy|dock|tablet|\\boled\\b|switch\\s*li(te|ght)|powera|power a|8bitdo|nacon|hori\\b|turtle beach|razer|gulikit|ipega|gamesir|bigben|snakebyte|thrustmaster|pdp\\b|afterglow|rock candy|easysmx|kompatibel|compatible|nachbau|replica|klon|clone|drittanbieter|third.?party|no.?name|china|generic|ähnlich|aehnlich|fake|nicht original|kein original|^\\W*(?:(?:verkaufe\\w*|biete|tausche|suche|neu\\w*|top|original\\w*|mein\\w{0,2})\\W+)*(sony\\s+|microsoft\\s+|nintendo\\s+)?(ps[45]|playstation\\s*[45]|xbox\\s+(series\\s+[xs]|one(\\s+[xs])?)|switch)\\b[^+]*?(\\+|\\bmit\\b|\\binkl\\.?|\\bund\\b|&)\\s*(\\d+\\s*)?(x\\s*)?(original\\s+)?(dualsense|dualshock|controller|pro\\s*controller|joy[- ]?cons?)|konsole|console|\\bdisc\\b|digital edition|\\b\\d+\\s?(tb|gb)\\b',
        'min': 10,
        'max': 45,
    },
    {
        'name': 'Joy-Con Paar',
        'match': 'joy[- ]?con',
        'exclude': '^(?:(?!\\b(?:auch|also)\\b).)*?\\bswitch\\s*2\\b|joy[- ]?cons?\\s*2\\b(?!\\s*(?:x|stk|stück))|konsole|console|ohne\\s*joy|dock|tablet|\\boled\\b|switch\\s*li(te|ght)|powera|power a|8bitdo|nacon|hori\\b|turtle beach|razer|gulikit|ipega|gamesir|bigben|snakebyte|thrustmaster|pdp\\b|afterglow|rock candy|easysmx|kompatibel|compatible|nachbau|replica|klon|clone|drittanbieter|third.?party|no.?name|china|generic|ähnlich|aehnlich|fake|nicht original|kein original|^\\W*(?:(?:verkaufe\\w*|biete|tausche|suche|neu\\w*|top|original\\w*|mein\\w{0,2})\\W+)*(sony\\s+|microsoft\\s+|nintendo\\s+)?(ps[45]|playstation\\s*[45]|xbox\\s+(series\\s+[xs]|one(\\s+[xs])?)|switch)\\b[^+]*?(\\+|\\bmit\\b|\\binkl\\.?|\\bund\\b|&)\\s*(\\d+\\s*)?(x\\s*)?(original\\s+)?(dualsense|dualshock|controller|pro\\s*controller|joy[- ]?cons?)|konsole|console|\\bdisc\\b|digital edition|\\b\\d+\\s?(tb|gb)\\b',
        'min': 20,
        'max': 80,
    },
    {
        'name': 'Switch 2 Pro Controller',
        'match': 'switch\\s*2.*pro[- ]?controller|pro[- ]?controller.*switch\\s*2',
        'exclude': '^(?:(?!\\bswitch\\s*2\\b).)*\\b(?:auch|also)\\b|powera|power a|8bitdo|nacon|hori\\b|turtle beach|razer|gulikit|ipega|gamesir|bigben|snakebyte|thrustmaster|pdp\\b|afterglow|rock candy|easysmx|kompatibel|compatible|nachbau|replica|klon|clone|drittanbieter|third.?party|no.?name|china|generic|ähnlich|aehnlich|fake|nicht original|kein original|^\\W*(?:(?:verkaufe\\w*|biete|tausche|suche|neu\\w*|top|original\\w*|mein\\w{0,2})\\W+)*(sony\\s+|microsoft\\s+|nintendo\\s+)?(ps[45]|playstation\\s*[45]|xbox\\s+(series\\s+[xs]|one(\\s+[xs])?)|switch)\\b[^+]*?(\\+|\\bmit\\b|\\binkl\\.?|\\bund\\b|&)\\s*(\\d+\\s*)?(x\\s*)?(original\\s+)?(dualsense|dualshock|controller|pro\\s*controller|joy[- ]?cons?)|konsole|console|\\bdisc\\b|digital edition|\\b\\d+\\s?(tb|gb)\\b',
        'min': 40,
        'max': 100,
    },
    {
        'name': 'Switch Pro Controller',
        'match': 'pro[- ]?controller',
        'exclude': 'joy[- ]?con|\\b(links|rechts|left|right|grip|paar)\\b|\\b(n64|snes|nes|sega|mega\\s*drive|gamecube)\\b|\\b(ps[345]|playstation\\s*[345]|xbox)\\b|^(?!.*switch).*\\bwii|^(?:(?!\\b(?:auch|also)\\b).)*?\\bswitch\\s*2\\b|powera|power a|8bitdo|nacon|hori\\b|turtle beach|razer|gulikit|ipega|gamesir|bigben|snakebyte|thrustmaster|pdp\\b|afterglow|rock candy|easysmx|kompatibel|compatible|nachbau|replica|klon|clone|drittanbieter|third.?party|no.?name|china|generic|ähnlich|aehnlich|fake|nicht original|kein original|^\\W*(?:(?:verkaufe\\w*|biete|tausche|suche|neu\\w*|top|original\\w*|mein\\w{0,2})\\W+)*(sony\\s+|microsoft\\s+|nintendo\\s+)?(ps[45]|playstation\\s*[45]|xbox\\s+(series\\s+[xs]|one(\\s+[xs])?)|switch)\\b[^+]*?(\\+|\\bmit\\b|\\binkl\\.?|\\bund\\b|&)\\s*(\\d+\\s*)?(x\\s*)?(original\\s+)?(dualsense|dualshock|controller|pro\\s*controller|joy[- ]?cons?)|konsole|console|\\bdisc\\b|digital edition|\\b\\d+\\s?(tb|gb)\\b',
        'min': 20,
        'max': 80,
    },
    {
        'name': 'Nintendo Switch 2',
        'match': '\\bswitch\\s*2\\b',
        'exclude': '^(?!.*(?:\\b(?:konsole|console|bundle)\\b|z[uü]beh[öo]r\\b\\W*(?:und\\W+)?ovp\\b|\\bovp\\b\\W*(?:und\\W+)?z[uü]beh[öo]r\\b))(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:z[uü]beh[öo]r|digitizer|\\bkontroller\\b|lenkr[aä]d|\\bwheel\\b|vr[- ]?brille|\\badapter\\b)|^(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:\\b(?:für|fuer|for)\\s+(?:(?:die|den|das|dem|the)\\s+)?(?:nintendo\\s+)?switch|steelbook|collector|sammler\\W?edition|limited\\s*run|signature\\s*edition|doppelpack|dual\\s*pack|double\\s*pack|remaster|(?<!kart 8 )deluxe\\s*(?:edition|set)|\\blabo\\b|poster|spannrahmen|entertainment\\s*system|world\\s*championships|micro\\s*sd|speicherkarte|sandisk|amiibo)|^(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+,]).)*?(?:doppelpack|dual\\s*pack|double\\s*pack)|^(?:(?!switch).)*?(?:steelbook|collector|sammler\\W?edition|limited\\s*run|signature\\s*edition|doppelpack|dual\\s*pack|double\\s*pack|remaster|(?<!kart 8 )deluxe\\s*(?:edition|set)|\\blabo\\b|poster|spannrahmen|entertainment\\s*system|world\\s*championships|micro\\s*sd|speicherkarte|sandisk|amiibo)|^(?:(?!switch).)*[(\\[]\\s*(?:nintendo\\s*)?switch(?:\\s*2)?\\s*(?:[&/,+]|[)\\]])|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b))(?:(?!switch).)*?(?:(?:pok[eé]mon|mario|zelda|kirby|luigi|yoshi|wario|donkey\\s*kong|metroid|animal\\s*crossing|splatoon|smash\\s*bros|xenoblade|fire\\s*emblem|bayonetta|mega\\s*man|rockman|yu[- ]?gi[- ]?oh|tomb\\s*raider|final\\s*fantasy|kingdom\\s*hearts|castlevania|spyro|rayman|bomberman|tetris|advance\\s*wars|need\\s*for\\s*speed|minecraft|\\bfifa\\b|\\blego\\b|\\bsonic\\b|asterix|digimon|dragon\\s*ball|harry\\s*potter|\\bdoom\\b|garfield)(?!\\s+(?:(?:pikachu|special|limited|center)\\s+)*edition))|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b))(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:\\bswitch\\s+sports\\b)|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b)).*\\bswitch(?:\\s*(?:2|oled|li(?:te|ght)))?\\s+\\w*tasche\\b|^(?!.*(?:defekt|kaputt|bastler)).*(?<!für )(?<!fuer )(?<!als )ersatzteil|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b)).*switch\\s*2\\s*edition|^(?=.*\\bswitch\\s*2\\b)(?:(?!\\bswitch\\s*2\\b).)*\\bswitch\\s*oled\\b',
        'veto': '^(?!(?=.*\\bswitch\\s*2\\b)(?:(?!\\bswitch\\s*2\\b).)*\\bswitch\\s*oled\\b)(?!.*(\\b(mit|inkl|inklusive|samt|plus|und|ohne)\\b|[+&])).*(controller|joy[- ]?con|gamepad|hülle|huelle|\\bcase\\b|tasche|schutzfolie|panzerglas|displayschutz|ladestation|ladekabel|netzteil|\\bdock\\b|amiibo|\\bgrips?\\b|\\bspiele?\\b|\\bgames?\\b|cartridge|\\bmodul\\b)|^(?!(?=.*\\bswitch\\s*2\\b)(?:(?!\\bswitch\\s*2\\b).)*\\bswitch\\s*oled\\b).*\\b(für|fuer|for)\\s+(die\\s+)?(nintendo\\s+)?switch\\s*2|\\bswitch\\s*(1|lite|light|v1|v2)\\b|^(?!(?=.*\\bswitch\\s*2\\b)(?:(?!\\bswitch\\s*2\\b).)*\\bswitch\\s*oled\\b).*\\bswitch\\s*oled\\b|kompatib|compatib|^(?!.*(\\b(mit|inkl|inklusive|samt|plus|und|ohne|konsole|console|bundle|set|disc|digital)\\b|[+&]|\\b\\d+\\s*(x\\s*)?(controller\\w*|gamepads?|pads?|joypads?)\\b|\\b\\d+\\s*(gb|tb)\\b)).*\\b(controller\\w*|gamepads?|pads?|joypads?)\\b(?![- ]?(stick|sticks|tasten?|knöpfe|knoepfe|port|anschluss|buchse|platine|akku))|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b|\\b(?:dock|tablet)\\b))(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?joy[- ]?con|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b)).*\\bswitch(?:\\s*(?:2|oled|li(?:te|ght)))?\\s+(?:(?:original\\w*|offiziell\\w*|wireless|kabel\\w*|bluetooth|schwarz\\w*|wei(?:ß|ss)\\w*|grau\\w*|neue[rn]?)\\s+)*(?:pro[- ]?)?(?:controller|kontroller)\\b(?![- ]?(?:stick|sticks|tasten?|knöpfe|knoepfe|port|anschluss|buchse|platine|akku))',
        'min': 200,
        'max': 550,
    },
    {
        'name': 'Switch nur Tablet',
        'match': 'switch.*(nur\\s*(das\\s*)?(tablet|konsole|gerät|geraet|display)|ohne\\s*(joy|dock|zubehör|zubehoer|controller)|tablet\\s*only|\\bhandheld\\s*only)',
        'exclude': 'oled|lite|switch\\s*light|netzwerk|gigabit|\\blan\\b|poe|managed|tp-?link|netgear|cisco|^(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und)\\b|[+&,]).)*?(\\bspiel(e|en)?\\b|\\bgames?\\b|hülle)',
        'veto': '\\bswitch\\s*2\\b|^(?!.*(\\b(mit|inkl|und|konsole|console)\\b|[+&])).*(?<!ohne )\\bcontroller(?![- ]?(stick|tasten?|knöpfe|knoepfe|port|anschluss|buchse))|^(?!.*(\\b(mit|inkl|inklusive|samt|plus|und|ohne|konsole|console|bundle|set|disc|digital)\\b|[+&]|\\b\\d+\\s*(x\\s*)?(controller\\w*|gamepads?|pads?|joypads?)\\b|\\b\\d+\\s*(gb|tb)\\b)).*\\b(controller\\w*|gamepads?|pads?|joypads?)\\b(?![- ]?(stick|sticks|tasten?|knöpfe|knoepfe|port|anschluss|buchse|platine|akku))',
        'min': 60,
        'max': 220,
    },
    {
        'name': 'Switch OLED',
        'match': 'switch.*oled|oled.*switch',
        'exclude': 'nur\\s*(das\\s*)?(tablet|konsole|gerät|geraet|display)|ohne\\s*(joy|dock|zubehör|zubehoer|controller)|tablet\\s*only|\\bhandheld\\s*only|^(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:\\bspiel(?:e|en)?\\b|\\bgames?\\b|hülle)|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|z[uü]beh[öo]r\\b\\W*(?:und\\W+)?ovp\\b|\\bovp\\b\\W*(?:und\\W+)?z[uü]beh[öo]r\\b))(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:z[uü]beh[öo]r|digitizer|\\bkontroller\\b|lenkr[aä]d|\\bwheel\\b|vr[- ]?brille|\\badapter\\b)|^(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:\\b(?:für|fuer|for)\\s+(?:(?:die|den|das|dem|the)\\s+)?(?:nintendo\\s+)?switch|steelbook|collector|sammler\\W?edition|limited\\s*run|signature\\s*edition|doppelpack|dual\\s*pack|double\\s*pack|remaster|(?<!kart 8 )deluxe\\s*(?:edition|set)|\\blabo\\b|poster|spannrahmen|entertainment\\s*system|world\\s*championships|micro\\s*sd|speicherkarte|sandisk|amiibo)|^(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+,]).)*?(?:doppelpack|dual\\s*pack|double\\s*pack)|^(?:(?!switch).)*?(?:steelbook|collector|sammler\\W?edition|limited\\s*run|signature\\s*edition|doppelpack|dual\\s*pack|double\\s*pack|remaster|(?<!kart 8 )deluxe\\s*(?:edition|set)|\\blabo\\b|poster|spannrahmen|entertainment\\s*system|world\\s*championships|micro\\s*sd|speicherkarte|sandisk|amiibo)|^(?:(?!switch).)*[(\\[]\\s*(?:nintendo\\s*)?switch(?:\\s*2)?\\s*(?:[&/,+]|[)\\]])|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b))(?:(?!switch).)*?(?:(?:pok[eé]mon|mario|zelda|kirby|luigi|yoshi|wario|donkey\\s*kong|metroid|animal\\s*crossing|splatoon|smash\\s*bros|xenoblade|fire\\s*emblem|bayonetta|mega\\s*man|rockman|yu[- ]?gi[- ]?oh|tomb\\s*raider|final\\s*fantasy|kingdom\\s*hearts|castlevania|spyro|rayman|bomberman|tetris|advance\\s*wars|need\\s*for\\s*speed|minecraft|\\bfifa\\b|\\blego\\b|\\bsonic\\b|asterix|digimon|dragon\\s*ball|harry\\s*potter|\\bdoom\\b|garfield)(?!\\s+(?:(?:pikachu|special|limited|center)\\s+)*edition))|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b))(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:\\bswitch\\s+sports\\b)|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b)).*\\bswitch(?:\\s*(?:2|oled|li(?:te|ght)))?\\s+\\w*tasche\\b|^(?!.*(?:defekt|kaputt|bastler)).*(?<!für )(?<!fuer )(?<!als )ersatzteil',
        'veto': '^(?:(?!\\bswitch\\s*oled\\b).)*\\bswitch\\s*2\\b|^(?!.*(\\b(mit|inkl|und|konsole|console)\\b|[+&])).*(?<!ohne )\\bcontroller(?![- ]?(stick|tasten?|knöpfe|knoepfe|port|anschluss|buchse))|^(?!.*(\\b(mit|inkl|inklusive|samt|plus|und|ohne|konsole|console|bundle|set|disc|digital)\\b|[+&]|\\b\\d+\\s*(x\\s*)?(controller\\w*|gamepads?|pads?|joypads?)\\b|\\b\\d+\\s*(gb|tb)\\b)).*\\b(controller\\w*|gamepads?|pads?|joypads?)\\b(?![- ]?(stick|sticks|tasten?|knöpfe|knoepfe|port|anschluss|buchse|platine|akku))|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b))(?:(?!switch).)*joy[- ]?con|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b)).*\\bswitch(?:\\s*(?:2|oled|li(?:te|ght)))?\\s+(?:(?:original\\w*|offiziell\\w*|wireless|kabel\\w*|bluetooth|schwarz\\w*|wei(?:ß|ss)\\w*|grau\\w*|neue[rn]?)\\s+)*(?:pro[- ]?)?(?:controller|kontroller)\\b(?![- ]?(?:stick|sticks|tasten?|knöpfe|knoepfe|port|anschluss|buchse|platine|akku))',
        'min': 150,
        'max': 380,
    },
    {
        'name': 'Switch Lite',
        'match': 'switch\\s*li(te|ght)\\b',
        'exclude': '^(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:\\bspiel(?:e|en)?\\b|\\bgames?\\b|hülle)|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|z[uü]beh[öo]r\\b\\W*(?:und\\W+)?ovp\\b|\\bovp\\b\\W*(?:und\\W+)?z[uü]beh[öo]r\\b))(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:z[uü]beh[öo]r|digitizer|\\bkontroller\\b|lenkr[aä]d|\\bwheel\\b|vr[- ]?brille|\\badapter\\b)|^(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:\\b(?:für|fuer|for)\\s+(?:(?:die|den|das|dem|the)\\s+)?(?:nintendo\\s+)?switch|steelbook|collector|sammler\\W?edition|limited\\s*run|signature\\s*edition|doppelpack|dual\\s*pack|double\\s*pack|remaster|(?<!kart 8 )deluxe\\s*(?:edition|set)|\\blabo\\b|poster|spannrahmen|entertainment\\s*system|world\\s*championships|micro\\s*sd|speicherkarte|sandisk|amiibo)|^(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+,]).)*?(?:doppelpack|dual\\s*pack|double\\s*pack)|^(?:(?!switch).)*?(?:steelbook|collector|sammler\\W?edition|limited\\s*run|signature\\s*edition|doppelpack|dual\\s*pack|double\\s*pack|remaster|(?<!kart 8 )deluxe\\s*(?:edition|set)|\\blabo\\b|poster|spannrahmen|entertainment\\s*system|world\\s*championships|micro\\s*sd|speicherkarte|sandisk|amiibo)|^(?:(?!switch).)*[(\\[]\\s*(?:nintendo\\s*)?switch(?:\\s*2)?\\s*(?:[&/,+]|[)\\]])|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b))(?:(?!switch).)*?(?:(?:pok[eé]mon|mario|zelda|kirby|luigi|yoshi|wario|donkey\\s*kong|metroid|animal\\s*crossing|splatoon|smash\\s*bros|xenoblade|fire\\s*emblem|bayonetta|mega\\s*man|rockman|yu[- ]?gi[- ]?oh|tomb\\s*raider|final\\s*fantasy|kingdom\\s*hearts|castlevania|spyro|rayman|bomberman|tetris|advance\\s*wars|need\\s*for\\s*speed|minecraft|\\bfifa\\b|\\blego\\b|\\bsonic\\b|asterix|digimon|dragon\\s*ball|harry\\s*potter|\\bdoom\\b|garfield)(?!\\s+(?:(?:pikachu|special|limited|center)\\s+)*edition))|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b))(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:\\bswitch\\s+sports\\b)|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b)).*\\bswitch(?:\\s*(?:2|oled|li(?:te|ght)))?\\s+\\w*tasche\\b|^(?!.*(?:defekt|kaputt|bastler)).*(?<!für )(?<!fuer )(?<!als )ersatzteil',
        'veto': '\\bswitch\\s*2\\b|^(?!.*(\\b(mit|inkl|und|konsole|console)\\b|[+&])).*(?<!ohne )\\bcontroller(?![- ]?(stick|tasten?|knöpfe|knoepfe|port|anschluss|buchse))|^(?!.*(\\b(mit|inkl|inklusive|samt|plus|und|ohne|konsole|console|bundle|set|disc|digital)\\b|[+&]|\\b\\d+\\s*(x\\s*)?(controller\\w*|gamepads?|pads?|joypads?)\\b|\\b\\d+\\s*(gb|tb)\\b)).*\\b(controller\\w*|gamepads?|pads?|joypads?)\\b(?![- ]?(stick|sticks|tasten?|knöpfe|knoepfe|port|anschluss|buchse|platine|akku))|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b))(?:(?!switch).)*joy[- ]?con|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b)).*\\bswitch(?:\\s*(?:2|oled|li(?:te|ght)))?\\s+(?:(?:original\\w*|offiziell\\w*|wireless|kabel\\w*|bluetooth|schwarz\\w*|wei(?:ß|ss)\\w*|grau\\w*|neue[rn]?)\\s+)*(?:pro[- ]?)?(?:controller|kontroller)\\b(?![- ]?(?:stick|sticks|tasten?|knöpfe|knoepfe|port|anschluss|buchse|platine|akku))',
        'min': 60,
        'max': 220,
    },
    {
        'name': 'Nintendo Switch',
        'match': 'nintendo\\s*switch|\\bswitch\\s*(konsole|v1|v2)\\b|^switch\\b',
        'exclude': 'oled|lite|switch\\s*light|(?<![a-zäöü])ports?\\b(?!\\W*(?:defekt|kaputt))|netzwerk|gigabit|\\blan\\b(?!\\W*adapter)|poe|managed|tp-?link|netgear|cisco|\\bhpe?\\b|aruba|procurve|ubiquiti|unifi|zyxel|d-?link|mikrotik|juniper|\\bethernet\\b(?!\\W*adapter)|rackmount|\\bsfp\\b|nur\\s*(das\\s*)?(tablet|konsole|gerät|geraet|display)|ohne\\s*(joy|dock|zubehör|zubehoer|controller)|tablet\\s*only|\\bhandheld\\s*only|^(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:\\bspiel(?:e|en)?\\b|\\bgames?\\b|hülle)|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|z[uü]beh[öo]r\\b\\W*(?:und\\W+)?ovp\\b|\\bovp\\b\\W*(?:und\\W+)?z[uü]beh[öo]r\\b))(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:z[uü]beh[öo]r|digitizer|\\bkontroller\\b|lenkr[aä]d|\\bwheel\\b|vr[- ]?brille|\\badapter\\b)|^(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:\\b(?:für|fuer|for)\\s+(?:(?:die|den|das|dem|the)\\s+)?(?:nintendo\\s+)?switch|steelbook|collector|sammler\\W?edition|limited\\s*run|signature\\s*edition|doppelpack|dual\\s*pack|double\\s*pack|remaster|(?<!kart 8 )deluxe\\s*(?:edition|set)|\\blabo\\b|poster|spannrahmen|entertainment\\s*system|world\\s*championships|micro\\s*sd|speicherkarte|sandisk|amiibo)|^(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+,]).)*?(?:doppelpack|dual\\s*pack|double\\s*pack)|^(?:(?!switch).)*?(?:steelbook|collector|sammler\\W?edition|limited\\s*run|signature\\s*edition|doppelpack|dual\\s*pack|double\\s*pack|remaster|(?<!kart 8 )deluxe\\s*(?:edition|set)|\\blabo\\b|poster|spannrahmen|entertainment\\s*system|world\\s*championships|micro\\s*sd|speicherkarte|sandisk|amiibo)|^(?:(?!switch).)*[(\\[]\\s*(?:nintendo\\s*)?switch(?:\\s*2)?\\s*(?:[&/,+]|[)\\]])|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b))(?:(?!switch).)*?(?:(?:pok[eé]mon|mario|zelda|kirby|luigi|yoshi|wario|donkey\\s*kong|metroid|animal\\s*crossing|splatoon|smash\\s*bros|xenoblade|fire\\s*emblem|bayonetta|mega\\s*man|rockman|yu[- ]?gi[- ]?oh|tomb\\s*raider|final\\s*fantasy|kingdom\\s*hearts|castlevania|spyro|rayman|bomberman|tetris|advance\\s*wars|need\\s*for\\s*speed|minecraft|\\bfifa\\b|\\blego\\b|\\bsonic\\b|asterix|digimon|dragon\\s*ball|harry\\s*potter|\\bdoom\\b|garfield)(?!\\s+(?:(?:pikachu|special|limited|center)\\s+)*edition))|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b))(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?(?:\\bswitch\\s+sports\\b)|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b)).*\\bswitch(?:\\s*(?:2|oled|li(?:te|ght)))?\\s+\\w*tasche\\b|^(?!.*(?:defekt|kaputt|bastler)).*(?<!für )(?<!fuer )(?<!als )ersatzteil',
        'veto': '\\bswitch\\s*2\\b|^(?!.*(\\b(mit|inkl|und|konsole|console)\\b|[+&])).*(?<!ohne )\\bcontroller(?![- ]?(stick|tasten?|knöpfe|knoepfe|port|anschluss|buchse))|^(?!.*(\\b(mit|inkl|inklusive|samt|plus|und|ohne|konsole|console|bundle|set|disc|digital)\\b|[+&]|\\b\\d+\\s*(x\\s*)?(controller\\w*|gamepads?|pads?|joypads?)\\b|\\b\\d+\\s*(gb|tb)\\b)).*\\b(controller\\w*|gamepads?|pads?|joypads?)\\b(?![- ]?(stick|sticks|tasten?|knöpfe|knoepfe|port|anschluss|buchse|platine|akku))|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b|\\b(?:dock|tablet)\\b))(?:(?!\\b(?:mit|inkl\\w*|inklusive|samt|plus|und|ohne)\\b|[+&,]).)*?joy[- ]?con|^(?!.*(?:\\b(?:konsole|console|bundle)\\b|\\b\\d+\\s*(?:gb|tb)\\b)).*\\bswitch(?:\\s*(?:2|oled|li(?:te|ght)))?\\s+(?:(?:original\\w*|offiziell\\w*|wireless|kabel\\w*|bluetooth|schwarz\\w*|wei(?:ß|ss)\\w*|grau\\w*|neue[rn]?)\\s+)*(?:pro[- ]?)?(?:controller|kontroller)\\b(?![- ]?(?:stick|sticks|tasten?|knöpfe|knoepfe|port|anschluss|buchse|platine|akku))',
        'min': 100,
        'max': 320,
    },
]
# fmt: on
BY = {g["name"]: g for g in REAL}

def named(title, grp, kind="device", qty=1, groups=REAL):
    r = from_classification(title, (grp, qty, kind), groups)
    return r and r[1] and r[1]["name"]

def test_exclude_of_the_named_group_rules_the_model_out():
    # Switch tablet only: the earlier group "Switch nur Tablet" takes it, Nintendo Switch excludes it
    t = "Switch nur Tablet ohne Joy-Con"
    assert match_group(t, REAL)["name"] == "Switch nur Tablet"
    assert from_classification(t, ("Nintendo Switch", 1, "device"), REAL) is None
    assert classified_market_group(t, 90, REAL, ("Nintendo Switch", 1, "device"))["name"] == "Switch nur Tablet"
    # Switch 2 Pro Controller is no Switch Pro Controller
    t = "Nintendo Switch 2 Pro Controller"
    assert from_classification(t, ("Switch Pro Controller", 1, "device"), REAL) is None
    assert classified_market_group(t, 60, REAL, ("Switch Pro Controller", 1, "device"))["name"] == \
        "Switch 2 Pro Controller"
    # Xbox 360 controller: "360" is in the exclude of Xbox Controller and no later group matches
    t = "Xbox 360 Controller"
    assert BY["Xbox Controller"]["exclude"] and match_group(t, REAL) is None
    assert from_classification(t, ("Xbox Controller", 1, "device"), REAL) is None
    assert classified_market_group(t, 20, REAL, ("Xbox Controller", 1, "device")) is None
    # bundles are judged the same way
    assert from_classification("Xbox 360 Controller + Ladekabel", ("Xbox Controller", 1, "bundle"), REAL) is None

def test_plain_titles_and_the_fall_through_keep_the_model():
    assert named("Nintendo Switch Konsole", "Nintendo Switch") == "Nintendo Switch"
    assert named("Xbox Series Controller schwarz", "Xbox Controller") == "Xbox Controller"
    assert named("Nintendo Switch Pro Controller", "Switch Pro Controller") == "Switch Pro Controller"
    # a console with Joy-Cons stays a bundle of the console, a Joy-Con pair "for Switch" stays a pair
    assert named("Nintendo Switch mit Joy-Con Paar", "Nintendo Switch", "bundle") == "Nintendo Switch"
    assert named("Joy-Con Paar für Nintendo Switch", "Joy-Con Paar") == "Joy-Con Paar"
    # exclude of Joy-Con einzeln hits (the title names a console), the word rules pass it on to the later
    # group Switch OLED: the model may overrule that fall-through, or a 20 EUR Joy-Con would be compared
    # with the console median
    t = "Original Nintendo Switch / OLED Joy-Con - Links Mario Red"
    assert match_group(t, REAL)["name"] == "Switch OLED"
    assert named(t, "Joy-Con einzeln") == "Joy-Con einzeln"
    assert classified_market_group(t, 20, REAL, ("Joy-Con einzeln", 1, "device"))["name"] == "Joy-Con einzeln"
    # a later group that only matches (its veto stops the title) does not take it: the exclude stands;
    # a config that wants the model to decide here puts that rule in soft_exclude
    t = "Nintendo Switch OLED Joy-Con Controller Paar Weiß"
    assert match_group(t, REAL) is None and named(t, "Joy-Con Paar") is None


def test_exclude_stands_when_no_later_group_takes_the_title():
    """Review 0.2.17: a later group that matches but excludes the title itself is no fall-through."""
    assert named("Nintendo Switch OLED nur Tablet", "Switch OLED") is None
    assert named("Joy-Con 2 rechts", "Joy-Con einzeln") is None
    assert named("Nintendo Switch 2 Joy-Con links", "Joy-Con einzeln") is None

def test_rule_with_small_groups():
    a = {"name": "A", "match": "ps5", "exclude": "slim|defekt"}
    b = {"name": "B", "match": "ps5 slim"}
    c = {"name": "C", "match": "ps5", "veto": "headset", "exclude": "edge"}
    groups = [a, b]
    assert named("PS5", "A", groups=groups) == "A"
    assert named("PS5 Slim", "A", groups=groups) == "A"          # falls through to B: the model may overrule
    assert named("PS5 defekt", "A", groups=groups) is None       # no later group matches: exclude stands
    assert named("PS5 Slim", "B", groups=groups) == "B"
    # an earlier group takes the title by the word rules: the later group's exclude stands
    groups = [b, c]
    assert named("PS5 Slim Edge", "C", groups=groups) is None
    assert named("PS5 Edge", "C", groups=groups) is None          # no later group
    assert named("PS5 Slim", "C", groups=groups) == "C"           # exclude does not hit: as before
    assert named("PS5 Headset", "C", groups=groups) is None       # veto, as before
    # unknown group or no match: as before
    assert named("PS5", "X", groups=groups) is None and named("Xbox", "C", groups=groups) is None
    assert from_classification("PS5 Slim Edge", (None, 1, "accessory"), groups) == ("accessory", None, 1)

def test_market_sample_leaves_out_the_excluded_classification():
    items = [{"title": "Xbox 360 Controller", "price": 20, "_cls": ("Xbox Controller", 1, "device")},
             {"title": "Xbox Series Controller", "price": 35, "_cls": ("Xbox Controller", 1, "device")},
             {"title": "Xbox One Controller schwarz", "price": 30, "_cls": ("Xbox Controller", 1, "device")}]
    cs = classified_sample(items, BY["Xbox Controller"], REAL, mc={"sample": "device_only"}, loc="de")
    assert sorted(p for p, *_ in cs["device"]) == [30, 35] and cs["unclassified"] == 0
    items = [{"title": "Switch nur Tablet ohne Joy-Con", "price": 90, "_cls": ("Nintendo Switch", 1, "device")}]
    assert classified_sample(items, BY["Nintendo Switch"], REAL, mc={"sample": "device_only"}, loc="de")["device"] == []
    # without a plausible classification it is an unclassified listing of the word-rule group
    assert classified_sample(items, BY["Switch nur Tablet"], REAL, mc={"sample": "device_only"},
                             loc="de")["unclassified"] == 1

def test_sold_by_group_clean_leaves_out_the_excluded_classification(tmp_path, monkeypatch):
    monkeypatch.setenv("DEAL_ENGINE_TODAY", "2026-11-15")
    con = history.connect(tmp_path / "h.db")
    rows = [("w-1", "Xbox 360 Controller", 20, "Xbox Controller"),
            ("w-2", "Xbox Series Controller", 35, "Xbox Controller"),
            ("w-3", "Nintendo Switch 2 Pro Controller", 60, "Switch Pro Controller"),
            ("w-4", "Nintendo Switch Pro Controller", 40, "Switch Pro Controller")]
    for i, (uid, title, price, grp) in enumerate(rows):
        con.execute("""INSERT INTO listing(uid, source, source_id, search, grp, title, defect, first_seen, last_seen,
                       price, status, gone_date, image) VALUES (?,?,?,?,?,?,0,?,?,?,'gone',?,?)""",
                    (uid, "willhaben", uid, "s", grp, title, "2026-11-01", "2026-11-05", price, "2026-11-05",
                     f"1/2/{i}_{1000000 + i}.jpg"))
        con.execute("INSERT INTO classify VALUES (?,?,?,?,?,?)", (uid, title, grp, 1, "device", "2026-11-01"))
    con.commit()
    sc = {"_name": "s", "_locale": "de", "market": {"groups": REAL, "sample": "device_only"}}
    old = history.sold_by_group(con, "s", 60)
    assert {g: sorted(s["p"]) for g, s in old.items()} == {"Xbox Controller": [20, 35],
                                                           "Switch Pro Controller": [40, 60]}
    new = history.sold_by_group(con, "s", 60, clean=history.sold_settings(sc))
    assert {g: s["p"] for g, s in new.items()} == {"Xbox Controller": [35], "Switch Pro Controller": [40]}
    con.close()


# ---------------------------------------------------------------------------- soft_exclude
from deal_engine.core.groups import check_groups as _check, from_classification as _fc, match_group as _mg  # noqa: E402

SOFT = [
    {"name": "Xbox One", "match": r"xbox\s*one", "soft_exclude": r"spiele|fifa", "exclude": r"controller",
     "veto": r"headset"},
    {"name": "Xbox Controller", "match": r"controller", "exclude": r"\b360\b"},
]


def test_soft_exclude_falls_through_like_exclude_for_word_rules():
    assert _mg("Xbox One S 2 Spiele", SOFT) is None
    assert _mg("Xbox One Controller", SOFT)["name"] == "Xbox Controller"
    assert _mg("Xbox One S 1TB", SOFT)["name"] == "Xbox One"


def test_classification_may_overrule_soft_exclude_but_not_exclude_or_veto():
    r = _fc("Xbox One S 2 Spiele", ("Xbox One", 1, "device"), SOFT)
    assert r is not None and r[1]["name"] == "Xbox One"
    assert _fc("Xbox 360 Controller", ("Xbox Controller", 1, "device"), SOFT) is None
    assert _fc("Xbox One Headset", ("Xbox One", 1, "device"), SOFT) is None


def test_soft_exclude_regex_is_checked():
    import pytest
    with pytest.raises(ValueError, match="soft_exclude"):
        _check([{"name": "X", "match": "x", "soft_exclude": "("}])
