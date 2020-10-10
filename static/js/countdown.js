SECOND = 1000;
MINUTE = 60 * SECOND;
HOUR = 60 * MINUTE;
DAY = 24 * HOUR;

function getFormatTime(timer)
{
    if (typeof(time_update) == "undefined") {
        time_update = DAY;
    }
    var h = parseInt(timer / 3600);
    var m = parseInt(timer % 3600 / 60);
    var s = parseInt(timer % 60);
    var c = parseInt(timer % 1 * 10);
    var d = parseInt((h + 12) / 24);
    if (h < 10) h = '0' + h;
    if (m < 10) m = '0' + m;
    if (s < 10 && h + m > 0) s = '0' + s;

    time_update = Math.min(time_update, HOUR);
    if (d > 2) return d + ' days';
    time_update = Math.min(time_update, SECOND);
    if (m + h > 0) return h + ':' + m + ':' + s;
    time_update = Math.min(time_update, SECOND / 10);
    return s + '.' + c;
}

function countdown()
{
    var need_reload = false;
    var now = $.now();

    $(".countdown").each(function () {
        var el = $(this)
        var timer
        if (el.is('[data-timestamp]')) {
            timer = parseInt($(this).attr('data-timestamp'))
        } else {
            timer = parseInt(el.find('.countdown-timestamp').html())
            el = $(el.find('.countdown-format')[0])
        }
        timer = timer - (now - page_load) / 1000
        var value;
        if (timer < 0) {
            need_reload = true;
            value = '--:--:--';
        } else {
            value = getFormatTime(timer);
        }
        el.html(value);
    });

    if (need_reload) {
        setTimeout("location.reload()", 1990);
    } else if (typeof(time_update) != "undefined") {
        setTimeout(countdown, time_update);
    }
}

$(function () {
    setTimeout(countdown, 0);
});
