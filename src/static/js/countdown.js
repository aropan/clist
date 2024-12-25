SECOND = 1000;
MINUTE = 60 * SECOND;
HOUR = 60 * MINUTE;
DAY = 24 * HOUR;
COUNTDOWN_RELOAD_DELAY = 10 * MINUTE;

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
    if (m < 10) m = '0' + m;
    if (s < 10 && h + m > 0) s = '0' + s;

    time_update = Math.min(time_update, HOUR);
    if (d > 2) return d + ' days';
    time_update = Math.min(time_update, MINUTE);
    if (h > 5) return h + ' hours';
    time_update = Math.min(time_update, SECOND);
    if (m + h > 0) return h + ':' + m + ':' + s;
    time_update = Math.min(time_update, SECOND / 10);
    return s + '.' + c;
}

var countdown_timeout = null;

function countdown()
{
    if (countdown_timeout) {
        clearTimeout(countdown_timeout);
    }
    countdown_timeout = null;

    var need_reload = false;
    var now = $.now();
    time_update = MINUTE;
    var reload_time_cookie_name = '_countdown_reload_time';

    $(".countdown").each(function () {
        var el = $(this)
        var timer
        var timestamp
        if (el.is('[data-timestamp]')) {
            timestamp = parseInt(el.attr('data-timestamp'))
            timer = timestamp - now / 1000
        } else if (el.is('[data-timestamp-up]')) {
            timestamp = parseInt(el.attr('data-timestamp-up'))
            timer = now / 1000 - timestamp
        } else {
            var delta = (now - page_load) / 1000
            if (el.is('[data-countdown]')) {
                timer = parseInt(el.attr('data-countdown'))
                timer = timer - delta
            } else if (el.is('[data-countdown-up]')) {
                timer = parseInt(el.attr('data-countdown-up'))
                timer = timer + delta
            } else {
                timer = parseInt(el.find('.countdown-timestamp').html())
                timer = timer - delta
                el = $(el.find('.countdown-format')[0])
            }
        }
        var value;
        if (timer < 0) {
            var countdown_reload_time = Cookies.get(reload_time_cookie_name)
            if (!countdown_reload_time || parseInt(countdown_reload_time) + COUNTDOWN_RELOAD_DELAY < now) {
                need_reload = true;
            }
            value = '0';
        } else {
            value = getFormatTime(timer)
            if (el.is('[data-timeago="true"]')) {
                value = $.timeago(timestamp * 1000)
            }
        }
        el.html(value);
    });

    if (need_reload) {
        Cookies.set(reload_time_cookie_name, now)
        setTimeout("location.reload()", 1990);
    } else if (typeof(time_update) != "undefined") {
        countdown_timeout = setTimeout(countdown, time_update);
    }
}

$(countdown)
