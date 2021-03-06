import xml.dom.minidom as minidom
from collections import OrderedDict
import jinja2
from lxml import etree
from django.shortcuts import render
from django.http import HttpResponse
from django.template import loader
from mwsu_curriculum import *
from jinja2 import Environment, FileSystemLoader
from pkg_resources import resource_filename


file_loader = FileSystemLoader('templates')


def index(request, ay=None):
    """ finds and displays the index.jinja template """
    if ay:
        return render(request, "index.jinja", {'years': available_years(), 'ay': ay})
    return render(request, "index.jinja", {'years': sorted(available_years())})


def offerings(request, ay):
    """ retrieves a summary of all courses offered over a two year period """
    return render(request, "offerings.jinja",
            {'courses': sorted(load_syllabi(ay), key=lambda s: s.subject+s.number),
             'hours_per_semester': hours_per_semester(ay), 'ay': ay})

def catalog(request, ay):
    return render(request, 'catalog.jinja', {'courses': sorted(load_syllabi(ay), key = lambda s : s.subject + s.number),
                                             'ay': ay})


def printable_syllabus(request, course, ay):
    """renders a course syllabus using the XSLT template in the curriculum lib"""
    xslt_doc = etree.parse(resource_filename('mwsu_curriculum', 'transformations/syllabus-to-html.xsl'))
    xslt_transformer = etree.XSLT(xslt_doc)
    coursexmlfile = resource_filename('mwsu_curriculum', 'syllabi/'+ay+'/'+course+'.xml')
    source_doc = etree.parse(coursexmlfile)
    output_doc = xslt_transformer(source_doc)
    return HttpResponse(output_doc)


def syllabus(request, course, ay):
    syllabus = load_syllabus(ay, course[0:3], course[3:])
    return render(request, "syllabus.jinja", {'syllabus': syllabus, 'ay': ay})


def load(request, ay):
    """ determines faculty load for the given academic year """
    roster = load_roster(ay)
    fall = load_schedule('fa', ay[2:4])
    spring = load_schedule('sp', ay[7:9])
    for instructor in roster:
        instructor.load = 0
        instructor.fallSections = []
        for release in instructor.releases:
            instructor.load += instructor.releases[release]
        for course in fall:
            for section in fall[course]:
                if section.instructorId == instructor.id:
                    instructor.load += section.workload_hours
                    instructor.fallSections.append(section)
        instructor.springSections = []
        for course in spring:
            for section in spring[course]:
                if section.instructorId == instructor.id:
                    instructor.load += section.workload_hours
                    instructor.springSections.append(section)

    return render(request, "load.jinja", {'roster': sorted(roster, key= lambda i:i.id), 'ay': ay})


def schedule(request, ay, semester):
    """ List teaching assignments for a single semester """
    alerts = []  # possible errors in the schedule to alert the reader to
    if semester == 'fa':
        year = ay[2:4]
    else:
        year = ay[7:9]
    courses = load_schedule(semester, year)
    sections = []
    for course in courses:
        sections = sections + courses[course]
    sections = sorted(sections, 
            key=lambda section : section.course.subject + str(section.course.number) + str(section.section))

    for section in sections:
        section.position = 0
    positions_modified = True
    daylengths = {'M':2, 'T': 2, 'W': 2, 'R': 2, 'F':1} # number of columns for each day in visualization
    while positions_modified:  # find overlapping sections and assign columns to them
        positions_modified = False
        for section in sections:
            for section2 in sections:
                if section is not section2  and section.conflicts_with(section2): # two overlapping sections
                    if section.instructorId == section2.instructorId: # instructors assigned to two simultaneous classes
                        alerts.append(section.course.subject+section.course.number + ' overlaps with ' + \
                                section2.course.subject+section2.course.number + ' and both are taught by ' + section.instructorId)
                    # TODO: repeat for rooms
                    if section.position == section2.position: # reposition on rendering
                        section2.position = section.position + 1
                        for day in daylengths:
                            if day in section2.days:
                                daylengths[day] = max(daylengths[day], section2.position+1)
                        positions_modified = True

    for section in sections: # parse start times to hours/minutes
        if section.startTime:
          hour, minutes = map(int, section.startTime.split(':'))
          if hour < 8:
              hour += 12
          hour -= 7  # start at 8am
          minutes += hour*60
          section.startPos = minutes

    # check for missing / extra courses
    required_courses = set(courses_in_semester(ay, semester))
    offered_courses = set()
    for section in sections:
        name = section.course.subject+section.course.number
        offered_courses.add(name)
        if name not in required_courses:
            alerts.append(name + ' not required this semester')
    for name in required_courses - offered_courses:
        alerts.append(name + ' required to be offered but not on schedule')
    print('required: ' + str(required_courses))
    print('offered: ' + str(offered_courses))


    roster = {}
    instructor_color= {}
    colors = ['red', 'blue', 'green', 'cyan', 'magenta', 'yellow', 
            'orange', 'chartreuse', 'azure', 'violet', 'salmon']
    i=0
    for instructor in load_roster(ay):
        roster[instructor.id] = instructor.name
        instructor_color[instructor.id] = colors[i]
        i += 1

    # determine offset for each day in visualization
    daypos = {
            'M': 0,
            'T': daylengths['M'],
            'W': daylengths['M'] + daylengths['T'],
            'R': daylengths['M'] + daylengths['T'] + daylengths['W'],
            'F': daylengths['M'] + daylengths['T'] + daylengths['W'] + daylengths['R']
    }
    return render(request, "teaching_assignments.jinja", 
            {'sections': sections, 'daypos': daypos, 'roster': roster,
                'instructor_color': instructor_color, 'ay': ay, 'alerts': alerts})


def standards(request, ay):
    """lists available curriculum standards"""
    standards = load_standards()
    ssorted = OrderedDict()
    for standard in sorted(standards):
        ssorted[standard] = standards[standard]
    return render(request, "curriculum_standards.jinja", {"standards": ssorted, 'ay': ay})

# Parse and pull all data from the acm-cs.xml file and returns all info within an array.
# this is used because of no xsl for this xml file
def standard(request, standard_id, ay, program_id=None):
    """ parses Standards then sets the information inside of the file to a list, this list is passed to the Template """
    standard = load_standard(standard_id)
    program = None
    if program_id:
        program = load_program(ay, program_id)
    if not program:
        for syllabus in load_syllabi(ay):
            standard.add_coverage(syllabus)
        return render(request, "curriculum_standard.jinja", {"standard": standard, 'ay': ay, 'programs': load_programs(ay)})
    else:
        for syllabus in program.available_courses():
            standard.add_coverage(syllabus)
        return render(request, "curriculum_standard.jinja", {"standard": standard, 'ay': ay, 'program': program})

def program(request, program_id, ay):
    program = load_program(ay, program_id)
    return render(request, "program.jinja", {'ay': ay, 'program': program})

def programs(request, ay):
    """lists available curriculum standards"""
    programs = load_programs(ay)
    psorted = OrderedDict()
    for program in sorted(programs):
        psorted[program] = programs[program]
    return render(request, "programs.jinja", {"programs": psorted, 'ay': ay})
