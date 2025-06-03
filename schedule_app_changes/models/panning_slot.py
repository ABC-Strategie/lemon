from odoo import models, api
from datetime import datetime, timedelta

class PlanningSlot(models.Model):
    _inherit = 'planning.slot'

    def create_timesheet_from_effective_hours(self, partner_id, start_date, end_date, specific_slot_id=None, specific_hours=None):
        """
        Create timesheet entries based on effective_hours or allocated_hours in planning.slot for a
        specific customer within a given date range, distributing 8 hours per day and splitting
        remaining hours to ensure no timesheet exceeds 8 hours. If hours remain after the date range,
        create a timesheet for the next day. If specific_slot_id is provided, use effective_hours or
        allocated_hours for that slot.
        :param partner_id: ID of the customer (res.partner)
        :param start_date: Start date for timesheet creation (e.g., '2025-05-16')
        :param end_date: End date for timesheet creation (e.g., '2025-05-19')
        :param specific_slot_id: ID of a specific slot to prioritize (optional)
        :param specific_hours: Ignored; hours are derived from effective_hours or allocated_hours (optional)
        """
        # Convert string dates to datetime objects
        try:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        except ValueError:
            return {'status': 'error', 'message': 'Invalid date format. Use YYYY-MM-DD.'}

        if start_date > end_date:
            return {'status': 'error', 'message': 'Start date cannot be after end date.'}

        # Fetch planning slots for the given customer with effective_hours or allocated_hours > 0
        domain = [
            ('resource_id', '=', partner_id),
            ('project_id.allow_timesheets', '=', True),
            '|',
            ('effective_hours', '>', 0),
            ('allocated_hours', '>', 0),
        ]
        if specific_slot_id:
            domain.append(('id', '=', specific_slot_id))
        slots = self.env['planning.slot'].search(domain)
        if not slots:
            return {'status': 'error', 'message': 'No planning slots found with effective or allocated hours for this customer.'}

        timesheet_env = self.env['account.analytic.line']
        created_timesheets = []
        max_hours_per_day = 8

        for slot in slots:
            # For specific slot, use effective_hours if > 0, else allocated_hours; otherwise, use slot's hours
            if specific_slot_id and slot.id == specific_slot_id:
                total_hours = slot.effective_hours if slot.effective_hours and slot.effective_hours > 0 else slot.allocated_hours
            else:
                total_hours = slot.effective_hours if slot.effective_hours and slot.effective_hours > 0 else slot.allocated_hours
            if total_hours <= 0:
                continue

            remaining_hours = total_hours
            # Calculate total days in the range
            total_days = (end_date - start_date).days + 1
            timesheet_data = []

            # Iterate over each day in the date range
            for day_offset in range(total_days):
                if remaining_hours <= 0:
                    break

                current_date = start_date + timedelta(days=day_offset)
                # Determine hours for the current day
                hours_for_day = min(remaining_hours, max_hours_per_day)

                # Check if a timesheet already exists for this slot and date
                existing_timesheet = timesheet_env.search([
                    ('slot_id', '=', slot.id),
                    ('employee_id', '=', slot.employee_id.id),
                    ('project_id', '=', slot.project_id.id),
                    ('date', '=', current_date),
                ])
                if not existing_timesheet:
                    timesheet_data.append({
                        'date': current_date,
                        'hours': hours_for_day,
                    })

                remaining_hours -= hours_for_day

            # Handle any remaining hours by creating timesheets on subsequent days
            current_date = end_date
            while remaining_hours > 0:
                current_date += timedelta(days=1)
                hours_for_day = min(remaining_hours, max_hours_per_day)

                # Check for existing timesheet
                existing_timesheet = timesheet_env.search([
                    ('slot_id', '=', slot.id),
                    ('employee_id', '=', slot.employee_id.id),
                    ('project_id', '=', slot.project_id.id),
                    ('date', '=', current_date),
                ])
                if not existing_timesheet:
                    timesheet_data.append({
                        'date': current_date,
                        'hours': hours_for_day,
                    })

                remaining_hours -= hours_for_day

            # Create timesheets from collected data
            for data in timesheet_data:
                timesheet_vals = {
                    'employee_id': slot.employee_id.id,
                    'project_id': slot.project_id.id,
                    'partner_id': slot.resource_id.id,
                    'date': data['date'],
                    'unit_amount': data['hours'],
                    'name': f"Timesheet from Planning Slot {slot.name or slot.id} - {data['date']}",
                    'slot_id': slot.id,
                }
                timesheet = timesheet_env.create(timesheet_vals)
                created_timesheets.append(timesheet.id)

        return {
            'status': 'success',
            'message': f'Created {len(created_timesheets)} timesheet entries.',
            'timesheet_ids': created_timesheets,
        }

    @api.model
    def action_generate_timesheets(self, partner_id, start_date, end_date, specific_slot_id=None, specific_hours=None):
        """
        Action to trigger timesheet creation for a specific customer within a date range.
        Can be called from a server action or button.
        :param specific_slot_id: ID of a specific slot to prioritize (optional)
        :param specific_hours: Ignored; hours are derived from effective_hours or allocated_hours (optional)
        """
        result = self.create_timesheet_from_effective_hours(partner_id, start_date, end_date, specific_slot_id, specific_hours)
        return result

    def action_publish(self):
        res = super().action_publish()
        if self.resource_id:
            # Example date range; adjust as needed
            start_date = str(self.start_datetime.date())
            end_date = str(self.end_datetime.date())
            # start_date = '2025-05-16'
            # end_date = '2025-05-19'
            # Pass specific slot ID; specific_hours is ignored as it's derived from slot
            self.action_generate_timesheets(
                self.resource_id.id,
                start_date,
                end_date,
                specific_slot_id=self.id
            )
        return res
