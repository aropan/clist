function filterCallbackCalendar(value) {
    calendar.refetchEvents()
}

$(function() {
    function get_calendar_height() {
        return $(window).height() - ($('#calendar').closest('.tab-content').position().top + 30)
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
        events: function (fetchInfo, successCallback, failureCallback) {
            $.ajax({
                url: '/get/events/',
                type: 'POST',
                traditional: true,
                headers: {
                    'X-CSRF-TOKEN': $('[name="csrf-token"]').attr('content')
                },
                data: {
                    start: fetchInfo.startStr,
                    end: fetchInfo.endStr,
                    categories: ['calendar'],
                    party: $('#party-name').attr('data-slug'),
                    search_query: $('#filter [type="text"]').val(),
                    ignore_filters:
                        $('.ignore-filter')
                        .filter(function () { return $(this).attr('data-value') == '1' })
                        .map(function () { return $(this).attr('data-id') })
                        .toArray(),
                },
                success: function (response) {
                    successCallback(response)
                },
                error: function(response) {
                    $.notify(response.responseJSON.message, 'error')
                    failureCallback({message: 'there was an error while fetching events!'})
                }
            });
        },
        eventRender: function (info) {
            var event = info.event
            var element = info.el
            var start = FullCalendarMoment.toMoment(event.start, calendar)
            var end = FullCalendarMoment.toMoment(event.end, calendar)
            var now = FullCalendarMoment.toMoment($.now(), calendar)
            var countdown = event.extendedProps.countdown;
            var title =
                    event.title
                    + '<div>' + event.extendedProps.host + '</div>'
                    + '<div>Start: ' + start.format('YYYY-MM-DD HH:mm') + '</div>'
                    + (event.end? '<div>End: ' + end.format('YYYY-MM-DD HH:mm') + '</div>' : '')
                    + (countdown?
                        '<div class="countdown">'
                        + (start < now? "Ends in " : "Starts in ")
                        + '<span class="countdown-timestamp hidden">'  + countdown + '</span>'
                        + '<span class="countdown-format">' + getFormatTime(countdown) + '</span>'
                        + '</div>' : '')
            $(element).tooltip({
                title: title,
                placement: 'top',
                container: 'body',
                html: true,
                delay: {
                    'show': 300,
                    'hide': 100,
                }
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
