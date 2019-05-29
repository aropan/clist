filterTimeoutUpdate = 2000

function filterCallback(value) {
    $('#calendar').fullCalendar('refetchEvents')
}

$(function() {
    function get_calendar_height() {
        return $(window).height() - 200;
    }

    $(window).resize(function() {
        $('#calendar').fullCalendar('option', 'height', get_calendar_height());
    });

    $('#calendar').fullCalendar({
        header: {
            left: 'prev,next today',
            center: 'title',
            right: 'month,basicWeek,basicDay'
        },
        firstDay: 1,
        timezone: timezone,
        events: {
            url: '/get/events/',
            type: 'GET',
            data: function() {
                var hide = []
                $('.ignore-filters')
                    .filter(function () { return $(this).attr('data-value') == '1' })
                    .each(function () { hide.push($(this).attr('data-id')) })
                return {
                    'cs': ['calendar'],
                    'if': hide,
                    'f': $('#filter [type="text"]').val(),
                }
            },
            error: function() {
                alert('there was an error while fetching events!');
            },
            cache: true
        },
        eventRender: function (event, element) {
            $(element).tooltip({
                placement: 'top',
                container: 'body',
                html: true,
                delay: {
                    'show': 300,
                    'hide': 100,
                },
                title:
                    event.title + ', ' + event.host +
                    '</br>Start: ' + event.start.format() +
                    (event.end? '</br>End: ' + event.end.format() : '')
            })
        },
        eventClick: function (data, event, view) {
            return true
        },
        loading: function(bool) {
            $('#loading').toggle(bool);
        },
        eventLimit: true,
        height: get_calendar_height()
    })

    $('.ignore-filters').click(function (e) {
        var $btn = $(this)
        var value = $btn.attr('data-value')
        $btn.attr('data-value', 1 - value)
        $btn.css('background-color', value == '0'? '#5BC0DE' : '#fff')
        $('#calendar').fullCalendar('refetchEvents')
        e.preventDefault()
        return false
    })
});
