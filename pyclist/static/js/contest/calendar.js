function filterCallbackCalendar(value) {
    calendar.refetchEvents()
}

$(function() {
    function get_calendar_height() {
        return $(window).height() - 150;
    }

    $(window).resize(function() {
        calendar.setOption('height', get_calendar_height())
    });

    calendar = new FullCalendar.Calendar($('#calendar')[0], {
        plugins: ['dayGrid', 'timeGrid', 'list', 'moment', 'momentTimezone'],
        customButtons: customButtonDesc,
        header: {
            left: 'title',
            right: customButtonGroup + ' today dayGridMonth,timeGridWeek,listWeek prev,next'
        },
        titleFormat: '{MMMM {D}}, YYYY',
        firstDay: 1,
        timezone: timezone,
        events: {
            url: '/get/events/',
            method: 'GET',
            extraParams: function() {
                var hide = []
                $('.ignore-filter')
                    .filter(function () { return $(this).attr('data-value') == '1' })
                    .each(function () { hide.push($(this).attr('data-id')) })
                return {
                    'cs': ['calendar'],
                    'if': hide,
                    'f': $('#filter [type="text"]').val()
                }
            }
        },
        eventRender: function (info) {
            var event = info.event
            var element = info.el
            var start = FullCalendarMoment.toMoment(event.start, calendar)
            var end = FullCalendarMoment.toMoment(event.end, calendar)
            $(element).tooltip({
                placement: 'top',
                container: 'body',
                html: true,
                delay: {
                    'show': 300,
                    'hide': 100,
                },
                title:
                    event.title +
                    '</br>Start: ' + start.format('YYYY-MM-DD HH:mm') +
                    (event.end? '</br>End: ' + end.format('YYYY-MM-DD HH:mm') : '')
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

    calendar.render()

    $('.fc-button').addClass('btn btn-default btn-sm').removeClass('fc-button fc-button-primary')
    $('.fc-button-group').addClass('btn-group').removeClass('fc-button-group')

    for (var name in customButtonDesc) {
        var desc = customButtonDesc[name]
        $('.fc-' + name + '-button').attr('data-id', desc.data)
    }

    if (customButtonSelector) {
        $(customButtonSelector).toggleClass('ignore-filter')
        $(customButtonSelector).click(function (e) {
            var $btn = $(this)
            var value = $btn.attr('data-value') || '0';
            $btn.attr('data-value', 1 - value)
            $btn.toggleClass('active')
            $btn.blur();
            e.preventDefault()
            calendar.refetchEvents()
            return false
        })
    }

    $('.fc-cb0-button').attr('id', 'spam-filter');
    $spam_filter = $('#spam-filter')
    $spam_filter.toggleClass('ignore-filter')
    $spam_filter.prop('checked', true)
    $spam_filter.bootstrapToggle({
        on: 'Filtered long',
        off: 'Disabled fitler',
        onstyle: 'info',
        offstyle: 'default',
        size: 'small',
        width: 106,
        height: 30,
    })
    $('.toggle:has(#spam-filter) .btn').click(function (e) {
        var value = $spam_filter.attr('data-value') || '0';
        $spam_filter.attr('data-value', 1 - value)
        $spam_filter.bootstrapToggle(parseInt(value)? 'on' : 'off')
        e.preventDefault()
        calendar.refetchEvents()
        return false
    })
})
