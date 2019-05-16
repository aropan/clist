function setCookie (name, value, expires, path, domain, secure) {
    document.cookie = name + "=" + escape(value) +
        ((expires) ? "; expires=" + expires : "") +
        ((path) ? "; path=" + path : "") +
        ((domain) ? "; domain=" + domain : "") +
        ((secure) ? "; secure" : "");
}

function selectOnChange(selectobj)
{
    setCookie(selectobj.id, selectobj.value, new Date(Date.parse(new Date()) + 365 * 24 * 60 * 60 * 1000).toString(), "/");
    window.location.reload();
//    location = location.href;
    return;
}

function timezoneOnChange(selectobj)
{
    alert(selectobj.id);
    var timezone = selectobj.value;
    setCookie("timezone", timezone, new Date(Date.parse(new Date()) + 365 * 24 * 60 * 60 * 1000).toString(), "/");
    window.location.reload();
//    location = location.href;
    return;

    var t = selectobj.options[selectobj.selectedIndex].getAttribute('data-time') * 1000;

    var a = document.getElementsByClassName('timezone');
    for (i = 0; i < a.length; i++)
    {
        var x = Date.parse(a[i].getAttribute('data-time'));
        var d = new Date(x + t);
        var s =
            ("0" + d.getUTCDate()).slice(-2) + '.' +
            ("0" + (d.getUTCMonth() + 1)).slice(-2) + '.' +
            d.getUTCFullYear() + '<br>' + 
            (("Sun,Mon,Tue,Wed,Thu,Fri,Sat,Sun").split(','))[d.getUTCDay()] + ', ' +
            ("0" + (d.getUTCHours())).slice(-2) + ':' +
            ("0" + (d.getUTCMinutes())).slice(-2);
        a[i].innerHTML = s;
    }
    var f = document.getElementById('calendarframe');
    if (f) f.src = f.getAttribute('lnk') + "&ctz=" + timezone;
}

function getFormatTime(timer)
{
    var h = parseInt(timer / 3600);
    var m = parseInt(timer % 3600 / 60);
    var s = parseInt(timer % 60);
    var c = parseInt(timer % 1 * 10);
    var d = parseInt((h + 12) / 24);
    if (h < 10) h = '0' + h;
    if (m < 10) m = '0' + m;
    if (s < 10 && h + m > 0) s = '0' + s;

    if (d > 2) return d + ' days';
    if (m + h > 0) return h + ':' + m + ':' + s;

    updateTime = 10;
    return s + '.' + c;
}

function countDown()
{
    var a = document.getElementsByClassName('countdown');

    updateTime = 1000;
    for (i = 0; i < a.length; i++)
    {
        var timer = parseInt(a[i].getAttribute('data-time')) - ((new Date()).getTime() - pageLoadTime);
        if (timer < 0)
        {
            location = location.href;
            window.location.reload();
            return;
            var s = '--:--:--';
        }
        else
        {
            var s = getFormatTime(timer / 1000);
        }

        if (s != a[i].innerHTML) a[i].innerHTML = s;
    }
    setTimeout("countDown()", updateTime);
}

function showHide()
{
    var obj = document.getElementById('resources');
    obj.style.display = obj.style.display == 'block'? 'none' : 'block';
}

function addValueChange(change)
{
    var atable = new Array('contest', 'resource');
    for (var key in atable)
    {
        var table = atable[key];
//        console.log(table);
        var afields = new Array();
        var avalues = new Array();

        var a = document.getElementsByClassName('add ' + table);
        for (i = 0; i < a.length; i++)
        {
            var obj = a[i];
            var field = obj.getAttribute('data-field');
            if (field == null) continue;

            var value = obj.value;
            if (!isInteger(value))
                value = '"' + escape(value) + '"';

            afields.push('`' + field + '`');
            avalues.push(value);
        }
        

        var obj = document.getElementById('aAdd_' + table);
        if (obj == null) return;
        obj.href = encodeURI('/?action=query&query=INSERT INTO `' + "clist_" + table + '` (' + afields.join(',') + ') VALUES (' + avalues.join(',') +')');
//        console.log(obj.href);
    }
}
