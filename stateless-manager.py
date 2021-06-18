import logging

import psutil
from plotmanager.print import pretty_print_bytes
import socket
import time

from datetime import datetime, timedelta

from plotmanager.configuration import get_config_info
from plotmanager.jobs import has_active_jobs_and_work, load_jobs, monitor_jobs_to_start
from plotmanager.log import check_log_progress
from plotmanager.processes import get_running_plots, get_system_drives
from plotmanager.notifications import send_notifications


chia_location, log_directory, config_jobs, manager_check_interval, max_concurrent, max_for_phase_1, \
    minimum_minutes_between_jobs, progress_settings, notification_settings, debug_level, view_settings, \
    instrumentation_settings = get_config_info()

logging.basicConfig(filename='run.log', format='%(asctime)s [%(levelname)s]: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', level=debug_level)

logging.info(f'Debug Level: {debug_level}')
logging.info(f'Chia Location: {chia_location}')
logging.info(f'Log Directory: {log_directory}')
logging.info(f'Jobs: {config_jobs}')
logging.info(f'Manager Check Interval: {manager_check_interval}')
logging.info(f'Max Concurrent: {max_concurrent}')
logging.info(f'Max for Phase 1: {max_for_phase_1}')
logging.info(f'Minimum Minutes between Jobs: {minimum_minutes_between_jobs}')
logging.info(f'Progress Settings: {progress_settings}')
logging.info(f'Notification Settings: {notification_settings}')
logging.info(f'View Settings: {view_settings}')
logging.info(f'Instrumentation Settings: {instrumentation_settings}')

logging.info(f'Loading jobs into objects.')
jobs = load_jobs(config_jobs)

next_periodic_report = datetime.now()
next_file_check = datetime.now()
next_log_check = datetime.now()
next_job_work = {}
running_work = {}

logging.info(f'Grabbing system drives.')
system_drives = get_system_drives()
logging.info(f"Found System Drives: {system_drives}")

logging.info(f'Grabbing running plots.')
jobs, running_work = get_running_plots(jobs=jobs, running_work=running_work,
                                       instrumentation_settings=instrumentation_settings)
for job in jobs:
    next_job_work[job.name] = datetime.now()
    max_date = None
    for pid in job.running_work:
        work = running_work[pid]
        start = work.datetime_start
        if not max_date or start > max_date:
            max_date = start
    initial_delay_date = datetime.now() + timedelta(minutes=job.initial_delay_minutes)
    if job.initial_delay_minutes:
        next_job_work[job.name] = initial_delay_date
    if not max_date:
        continue
    max_date = max_date + timedelta(minutes=job.stagger_minutes)
    if job.initial_delay_minutes and initial_delay_date > max_date:
        logging.info(f'{job.name} Found. Setting initial dalay date to {next_job_work[job.name]} which is '
                     f'{job.initial_delay_minutes} minutes.')
        continue
    next_job_work[job.name] = max_date
    logging.info(f'{job.name} Found. Setting next stagger date to {next_job_work[job.name]}')

if minimum_minutes_between_jobs and len(running_work.keys()) > 0:
    logging.info(f'Checking to see if stagger needs to be altered due to minimum_minutes_between_jobs. '
                 f'Value: {minimum_minutes_between_jobs}')
    maximum_start_date = max([work.datetime_start for work in running_work.values()])
    minimum_stagger = maximum_start_date + timedelta(minutes=minimum_minutes_between_jobs)
    logging.info(f'All dates: {[work.datetime_start for work in running_work.values()]}')
    logging.info(f'Calculated Latest Job Start Date: {maximum_start_date}')
    logging.info(f'Calculated Minimum Stagger: {minimum_stagger}')
    for job_name in next_job_work:
        if next_job_work[job_name] > minimum_stagger:
            logging.info(f'Skipping stagger for {job_name}. Stagger is larger than minimum_minutes_between_jobs. '
                         f'Minimum: {minimum_stagger}, Current: {next_job_work[job_name]}')
            continue
        next_job_work[job_name] = minimum_stagger
        logging.info(f'Setting a new stagger for {job_name}. minimum_minutes_between_jobs is larger than assigned '
                     f'stagger. Minimum: {minimum_stagger}, Current: {next_job_work[job_name]}')

logging.info(f'Starting loop.')

while has_active_jobs_and_work(jobs):

    # CHECK LOGS FOR DELETED WORK
    logging.info(f'Checking log progress..')
    check_log_progress(jobs=jobs, running_work=running_work, progress_settings=progress_settings,
                       notification_settings=notification_settings, view_settings=view_settings,
                       instrumentation_settings=instrumentation_settings)
    next_log_check = datetime.now() + timedelta(seconds=manager_check_interval)

    # Report from time to time
    if (datetime.now() > next_periodic_report):
        totalwork = 0
        str = ""

        for job in jobs:
            totalwork = totalwork + job.total_running
            for pid in job.running_work:
                if (pid in running_work):
                    work = running_work[pid]
                    str += f'[{work.plot_id[:7]}, phase {work.current_phase} on {work.temporary_drive} ({work.progress}), started {work.datetime_start})]\n'
                #except:
                #    print("Something went wrong with the jobs listing.")

        ram_usage = psutil.virtual_memory()
        send_notifications(
            title='Plotting report',
            body=f'Periodic report for [{socket.gethostname()}].\n{totalwork} plotting tasks running.\nCPU usage: {psutil.cpu_percent()}%\nRAM Usage: {pretty_print_bytes(ram_usage.used, "gb")}/{pretty_print_bytes(ram_usage.total, "gb", 2, "GiB")} ({ram_usage.percent}%). \n{str}',
            settings=notification_settings
        )
        next_periodic_report = datetime.now() + timedelta(seconds=3600)

    # # Check for zombie files
    # if (datetime.now() > next_file_check):

    #     listOfWork = []
    #     # create a list of all "work"
    #     for job in jobs:
    #         for pid in running_work:
    #             if (pid in running_work):
    #                 listOfWork.append(work.plot_id)
        
    #     # scan all temp folders
    #     for job in jobs:
    #         for    

    #    next_file_check = datetime.now() + timedelta(seconds=30)

    # DETERMINE IF JOB NEEDS TO START
    logging.info(f'Monitoring jobs to start.')
    jobs, running_work, next_job_work, next_log_check = monitor_jobs_to_start(
        jobs=jobs,
        running_work=running_work,
        max_concurrent=max_concurrent,
        max_for_phase_1=max_for_phase_1,
        next_job_work=next_job_work,
        chia_location=chia_location,
        log_directory=log_directory,
        next_log_check=next_log_check,
        minimum_minutes_between_jobs=minimum_minutes_between_jobs,
        system_drives=system_drives,
    )

    logging.info(f'Sleeping for {manager_check_interval} seconds.')
    time.sleep(manager_check_interval)

logging.info(f'Manager has exited loop because there are no more active jobs.')
