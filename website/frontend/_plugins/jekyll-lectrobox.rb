module Jekyll

  # Generator that turns the projects listed in _data/projects.yml into nav bar
  # contents
  class NavBarGenerator < Jekyll::Generator
    def generate(site)
      # iterate over each project tag
      site.data["project-tags"].each do |tag|

        # for each tag, build a list of the projects that have the tag
        projects = []
        site.data["projects"].each do |project|
          if not project.key?("tags")
            next
          end
          if project["tags"].include? tag["tag"]
            projects << {
              "title" => project["title"],
              "url" => project["url"],
            }
          end
        end

        if projects.length > 0
          # add all the tag's projects to the nav bar with the list of projects we
          # found
          site.data["navigation"] << {
            "title" => tag["title"],
            "side" => "left",
            "dropdown" => projects
          }
        end
      end
    end
  end

  # simple example of a tag (unused, just didn't want to lose this recipe)
  class ProjectList < Liquid::Tag
    def initialize(tag_name, text, tokens)
      super
      @text = text
    end

    def render(context)
      context.registers[:page]["projects"].each do |project|
        puts('here is a project')
        inc = "{% include _frontpage-widget.html widget=page.projects[0] %}"
        Liquid::Template.parse(inc).render(context)
      end
      output
    end
  end
end

Liquid::Template.register_tag('project_list', Jekyll::ProjectList)
